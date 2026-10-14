from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from test_sermon_listener_directives import Sdk, adapter, block, context
from test_sermon_public_life_review import raw_block
from pastor_transcript_extractor.cli import app
from pastor_transcript_extractor.sermon_classifier_typesafe import TypeSafeBlockCache
from pastor_transcript_extractor.sermon_leaf_packs import SOURCE_MATERIAL as PACK, LISTENER_DIRECTIVES, PUBLIC_LIFE_TREATMENT
from pastor_transcript_extractor.sermon_listener_directive_review import evaluate_review, fingerprint, write_review
from pastor_transcript_extractor.sermon_source_material_review import SOURCE_PROBE_PATH, prepare_source_review, source_material_route, select_source_cases
from pastor_transcript_extractor.sermon_topics import TOPIC_PACK_VERSION


class SourceMaterialTests(unittest.TestCase):
    def test_contract_covers_overlap_and_target_attribution_without_changing_frozen_packs(self):
        probes = json.loads(SOURCE_PROBE_PATH.read_text())
        self.assertEqual(23, len(probes))
        self.assertEqual(set(PACK.definitions), {k for p in probes for k in p['expected_positive_leaves']})
        self.assertTrue(any(len(p['expected_positive_leaves']) > 1 for p in probes))
        self.assertTrue(any(p.get('leading_context') and not p['expected_positive_leaves'] for p in probes))
        self.assertIn('missing source or material', str(PACK.questions(0)))
        self.assertNotEqual(PACK.digest(), replace(PACK, missing_evidence='testimony').digest())
        for path, spec in [('listener-directives-review-v3.json', LISTENER_DIRECTIVES),
                           ('public-life-treatment-review-v2.json', PUBLIC_LIFE_TREATMENT)]:
            frozen = json.loads((Path('evaluation/sermon-topics') / path).read_text())
            self.assertEqual(frozen['question_pack_digest'], spec.digest())

    def test_route_and_selection_do_not_gate_on_topic_or_cues(self):
        for value in (False, 'true', 1, None):
            self.assertFalse(source_material_route({'projection_eligibility': {'eligible': value}})['route'])
        self.assertTrue(source_material_route({'projection_eligibility': {'eligible': True}})['route'])
        items = [{'block_id': i, 'target_text': text, 'projection_eligibility': {'eligible': i != 4}}
                 for i, text in enumerate(('Jesus rescued Peter.', 'My experience of faith.', 'Ellen White writes.', 'Be patient.', 'Jesus spoke.'))]
        chosen = select_source_cases(items)
        self.assertEqual(4, len(chosen))
        self.assertEqual(chosen, select_source_cases(list(reversed(items))))
        self.assertNotIn(4, [c['block_id'] for c in chosen])
        fallback = select_source_cases([{**b, 'target_text': 'Be patient.'} for b in items])
        self.assertEqual(4, len(fallback))
        self.assertEqual(4, len({c['block_id'] for c in fallback}))

    def prepare(self, directory):
        source = Path(directory) / 'classification.json'
        source.write_text('cached')
        raw = [raw_block(i, 0., i != 4) for i in range(5)]
        for item, text in zip(raw, ('Jesus rescued Peter.', 'My experience of faith.', 'Ellen White writes.', 'Be patient.', 'Jesus spoke.')):
            item['context']['target_text'] = text
        database = SimpleNamespace(database_path=source, get_video_by_id=lambda i: SimpleNamespace(id=i, title='Sources'))
        gate = SimpleNamespace(eligible=True, source_path=source, topic_analysis_fingerprint='frozen')
        module = 'pastor_transcript_extractor.sermon_listener_directive_review'
        with patch(module + '.assess_topic_profile_projection', return_value=gate), \
             patch(module + '.read_topic_analysis_for_gate', return_value=({'question_pack_version': TOPIC_PACK_VERSION, 'blocks': raw}, {})), \
             patch(module + '.resolve_topic_block_context', side_effect=lambda b: b['context']):
            packet = prepare_source_review(database, model='jev-1.13.0', probe_cache=Path(directory)/'probes')
        for case in packet['cases']:
            if isinstance(case['video_id'], int):
                case['cache_dir'] += str(case['video_id'])
        packet.pop('input_fingerprint')
        packet['input_fingerprint'] = fingerprint(packet)
        return packet

    def test_bounded_evaluation_and_output_repair_reuse_only_source_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            packet = self.prepare(directory)
            self.assertEqual(35, len(packet['cases']))
            self.assertEqual(3, len(packet['excluded_content_controls']))
            self.assertTrue(all(c['route']['route'] for c in packet['cases'] if c['video_id'] != 'contract-probes'))
            sdk = Sdk()
            first, execution = evaluate_review(packet, pack=PACK, client=adapter(sdk))
            self.assertGreater(execution['provider_requests'], 0)
            self.assertEqual(210, sum(len(q) for state, q in sdk.requests))
            self.assertTrue(all(list(state) == [PACK.state_key] for state, q in sdk.requests))
            repeated, execution = evaluate_review(packet, pack=PACK, client=adapter(sdk))
            self.assertEqual(0, execution['provider_requests'])
            self.assertEqual(first, repeated)
            output = Path(directory)/'review.json'
            self.assertFalse(write_review(output, first, title='Sources')[2])
            self.assertTrue(write_review(output, first, title='Sources')[2])
            output.with_suffix('.md').write_text('broken')
            self.assertFalse(write_review(output, first, title='Sources')[2])
            corrupt = deepcopy(packet)
            corrupt['cases'][0]['target_text'] = 'changed'
            with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
                evaluate_review(corrupt, pack=PACK, client=adapter(sdk))

    def test_changed_batch_replays_and_context_change_invalidates_only_affected_block(self):
        with tempfile.TemporaryDirectory() as directory:
            sdk = Sdk()
            cache = TypeSafeBlockCache(Path(directory), model='jev-1.13.0')
            a, b = block(0), block(1)
            def assess(items, contexts):
                return cache.assess_packs(adapter(sdk), {}, items, requested_packs=frozenset({PACK.version}), topic_contexts=contexts)
            assess([a, b], {a.block_id: context(a), b.block_id: context(b)})
            assess([b], {b.block_id: context(b)})
            self.assertEqual(1, len(sdk.requests))
            changed = replace(context(a), leading_context='We are reading Ellen White.')
            assess([a, b], {a.block_id: changed, b.block_id: context(b)})
            self.assertEqual(2, len(sdk.requests))
            self.assertEqual(6, len(sdk.requests[-1][1]))

    def test_cli_prepare_and_lazy_cache_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            packet = self.prepare(directory)
            sdk = Sdk()
            evaluate_review(packet, pack=PACK, client=adapter(sdk))
            module = 'pastor_transcript_extractor.commands.analysis.content'
            with patch('pastor_transcript_extractor.sermon_source_material_review.prepare_source_review', return_value=packet), \
                 patch(module + '.Database') as database_factory, patch(module + '.TypeSafeSdkAdapter', side_effect=AssertionError('Provider must stay lazy')):
                output = Path(directory)/'cli.json'
                for options in (['--prepare-only'], [], []):
                    result = CliRunner().invoke(app, ['analysis', 'source-material-review', '--output', str(output), *options])
                    self.assertEqual(0, result.exit_code, result.output + str(result.exception))
                    self.assertIn('provider_requests=0', result.output)
                self.assertIn('Reused', result.output)
                self.assertTrue(database_factory.call_args.kwargs['readonly'])


if __name__ == '__main__':
    unittest.main()
