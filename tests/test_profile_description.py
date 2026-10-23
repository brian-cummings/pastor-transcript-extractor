from copy import deepcopy
import re
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from pastor_transcript_extractor import profile_description as d
from pastor_transcript_extractor import segment_cache_inventory as m
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal


def fixture(*, routed=False, measured=True, text='A quoted view is discussed, not adopted. <script>unsafe()</script>'):
    block = dict(block_id=1, start_seconds=0, end_seconds=60, segment_indexes=[0],
        resolved_model_id=m.DEFAULT_TYPESAFE_MODEL, projection_eligibility={'eligible': True},
        context={'leading_context': '', 'target_text': text, 'trailing_context': '', 'diagnostics': {}}, scores={k: dict(score=0, probabilities={str(i): float(i == 0) for i in range(5)}) for k in m.TOPIC_SPECS})
    if routed:
        block['scores']['salvation_gospel'] = dict(score=3, probabilities={str(i): float(i == 3) for i in range(5)})
    projection = dict(eligible_block_ids=[1], measurements={k: dict(mean_normalized_expected_prominence=0.1,
        mean_supporting_or_above_probability=0.2, representative_blocks=[dict(block_id=1)], counterevidence_blocks=[dict(block_id=1)]) for k in m.TOPIC_SPECS})
    analysis = dict(question_pack_version=m.TOPIC_PACK_VERSION, question_pack_digest=m.topic_pack_digest(),
        requested_model_id=m.DEFAULT_TYPESAFE_MODEL, blocks=[block], sermon_projection=projection)
    common = {k: block[k] for k in ('block_id', 'start_seconds', 'end_seconds', 'segment_indexes', 'resolved_model_id')}
    semantic = dict(question_version=m.SEMANTIC_ANALYSIS_QUESTION_VERSION, dimensions=list(m.SEMANTIC_DIMENSIONS),
        blocks=[dict(**common, probabilities={k: 0.1 for k in m.SEMANTIC_DIMENSIONS})])
    s = m.salvation
    probabilities = {k: 0.01 for k in s.SALVATION_RELATIONSHIPS}
    probabilities['divine_grace_initiative'] = 0.99
    raw_sal = dict(question_pack_version=s.SALVATION_RELATIONSHIPS_PACK_VERSION,
        question_pack_digest=s.salvation_relationship_pack_digest(), requested_model_id=m.DEFAULT_TYPESAFE_MODEL,
        observation_policy_version=s.SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
        observation_thresholds=s.SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
        measurement_statuses=s.SALVATION_RELATIONSHIP_MEASUREMENT_STATUSES,
        route_policy_version=s.SALVATION_ROUTE_POLICY_VERSION, route_threshold=s.SALVATION_ROUTE_THRESHOLD,
        final_projection_reconciled=True, missing_current_routed_block_ids=[], blocks=[])
    if routed and measured:
        raw_sal['blocks'] = [dict(**common, context=block['context'], route={'route': True}, probabilities=probabilities,
            observations=[dict(relationship=k) for k in s.collected_salvation_relationships(probabilities)])]
    classification = dict(search=dict(topic_analysis=analysis, semantic_analysis=semantic, salvation_relationship_analysis=raw_sal))
    layers = m.compatible_layers(classification, analysis, [1])
    topic = next(iter(m.TOPIC_SPECS))
    measurement = m.topics_projection._projection_measurements(projection)[topic]
    sermon = dict(video_id=9, title='Source <unsafe>', url='https://youtu.be/example', source_path='/source.json', source_sha256='abc',
        model=m.DEFAULT_TYPESAFE_MODEL, gate={'eligible': True}, eligible_blocks=1, eligible_block_ids=[1],
        salvation_measured_blocks=len(layers['salvation']), treatment=layers['treatment'], salvation=layers['salvation'],
        topic_examples=[dict(block_id=1, topic=topic, label=m.TOPIC_SPECS[topic].label, full_target_text=text,
            start_seconds=0, end_seconds=60, scores=block['scores'][topic], existing_sermon_measurement=measurement)])
    inventory = seal(dict(selected_profile=dict(id=17, display_label=None, membership_fingerprint='membership'), sermons=[sermon], gaps=[],
        coverage=dict(eligible_topic_blocks=1, salvation_measured_blocks=len(layers['salvation']), unresolved_salvation_leaves=list(s.UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS))))
    return inventory, {9: dict(classification=classification)}


class DescriptionTests(unittest.TestCase):
    def test_no_adoption_from_identical_topic_in_quoted_or_affirmed_text(self):
        for text in ('He quotes someone saying salvation is earned.', 'He affirms salvation is earned.'):
            record = d.build(*fixture(text=text))
            self.assertTrue(all(c['rule'] == 'topic' for c in record['claims']))
            self.assertIn('not establish agreement', record['claims'][0]['wording'])
            self.assertTrue(any(g['id'] == 'adoption' for g in record['gaps']))

    def test_lower_treatment_probabilities_never_admit_a_style_trait(self):
        record = d.build(*fixture())
        self.assertEqual(4, len(record['treatment_candidates']))
        self.assertTrue(all(c['status'] == 'inspection_candidate_only' for c in record['treatment_candidates']))
        self.assertFalse(any(c['rule'] == 'treatment' for c in record['claims']))

    def test_unrouted_missing_below_threshold_and_unresolved_are_distinct(self):
        record = d.build(*fixture())
        self.assertEqual('unrouted_unmeasured', record['salvation_block_states'][0]['state'])
        record = d.build(*fixture(routed=True, measured=False))
        self.assertEqual('missing_compatible_routed_result', record['salvation_block_states'][0]['state'])
        record = d.build(*fixture(routed=True))
        states = {o['state'] for o in record['observations'] if o['layer'] == 'salvation'}
        self.assertEqual({'observed', 'measured_below_threshold'}, states)
        self.assertEqual(1, sum(c['rule'] == 'salvation' for c in record['claims']))
        self.assertTrue(record['unresolved_leaves'])
        self.assertFalse(any(o['field'] in record['unresolved_leaves'] for o in record['observations']))

    def test_all_below_threshold_remains_measured_without_positive_claim(self):
        inv, sources = fixture(routed=True)
        raw = sources[9]['classification']['search']['salvation_relationship_analysis']['blocks'][0]
        raw['probabilities'] = {k: 0.01 for k in raw['probabilities']}
        raw['observations'] = []
        a = sources[9]['classification']['search']['topic_analysis']
        layers = m.compatible_layers(sources[9]['classification'], a, [1])
        inv = deepcopy(inv); inv['sermons'][0]['salvation'] = layers['salvation']
        record = d.build(seal(inv), sources)
        self.assertEqual('measured_local_only', record['dimensions'][2]['status'])
        self.assertFalse(any(c['rule'] == 'salvation' for c in record['claims']))
        self.assertEqual({'measured_below_threshold'}, {o['state'] for o in record['observations'] if o['layer'] == 'salvation'})

    def test_missing_treatment_is_not_low_or_measured(self):
        inv, sources = fixture()
        sources[9]['classification']['search']['semantic_analysis']['blocks'] = []
        inv = deepcopy(inv); inv['sermons'][0]['treatment'] = []
        record = d.build(seal(inv), sources)
        self.assertEqual([], record['treatment_candidates'])
        self.assertEqual('unmeasured', record['dimensions'][0]['status'])
        self.assertEqual('unmeasured', record['dimensions'][3]['status'])

    def test_source_contract_or_eligibility_changes_are_rejected(self):
        for mutate in (
            lambda a: a.update(question_pack_digest='changed'),
            lambda a: a['blocks'][0]['projection_eligibility'].update(eligible=False),
            lambda a: a['sermon_projection'].update(eligible_block_ids=[]),
            lambda a: a['blocks'].append(deepcopy(a['blocks'][0])),
        ):
            inv, sources = fixture()
            mutate(sources[9]['classification']['search']['topic_analysis'])
            with self.assertRaises(ValueError): d.build(inv, sources)

    def test_overlapping_windows_and_duplicate_recordings_are_rejected(self):
        inv, sources = fixture()
        inv = deepcopy(inv); inv['sermons'].append(deepcopy(inv['sermons'][0]))
        with self.assertRaises(ValueError): d.build(seal(inv), sources)
        inv, sources = fixture()
        a = sources[9]['classification']['search']['topic_analysis']
        a['blocks'].append(dict(deepcopy(a['blocks'][0]), block_id=2, start_seconds=30, end_seconds=90))
        a['sermon_projection']['eligible_block_ids'] = [1, 2]
        inv = deepcopy(inv); inv['sermons'][0]['eligible_block_ids'] = [1, 2]
        with self.assertRaisesRegex(ValueError, 'Overlapping'): d.build(seal(inv), sources)

    def test_counterevidence_and_complete_summary_inputs_are_linked(self):
        record = d.build(*fixture())
        claim = record['claims'][0]
        self.assertEqual(claim['observation_input_ids'], claim['counterevidence_ids'])
        self.assertTrue(claim['observation_input_ids'])
        self.assertIn('counterevidence', d.render(record))

    def test_escaping_navigation_and_all_internal_targets(self):
        record = d.build(*fixture(routed=True))
        page = d.render(record)
        self.assertNotIn('<script>unsafe()', page)
        self.assertIn('&lt;script&gt;unsafe()', page)
        self.assertIn('Source &lt;unsafe&gt;', page)
        ids = re.findall(r' id="([^"]+)"', page)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(set(re.findall(r'href="#([^"]+)"', page)) <= set(ids))
        self.assertIn('hashchange', page)
        self.assertIn('Filter recordings', page)
        self.assertLess(page.index('Assessment of this sample'), page.index('Pastor at a glance'))
        self.assertLess(page.index('Pastor at a glance'), page.index('Sermons and supporting passages'))

    def test_deterministic_pure_assembly_and_identity_invalidation(self):
        inv, sources = fixture(); before = deepcopy((inv, sources))
        first = d.build(inv, sources)
        self.assertEqual(before, (inv, sources))
        self.assertEqual(first, d.build(inv, sources))
        changed = deepcopy(inv); changed['selected_profile']['membership_fingerprint'] = 'new'
        self.assertNotEqual(first['content_fingerprint'], d.build(seal(changed), sources)['content_fingerprint'])

    def test_leaf_reuse_probe_is_bounded_and_read_only(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from pastor_transcript_extractor.sermon_classifier_typesafe import TypeSafeBlockCache
        inv, sources = fixture()
        with TemporaryDirectory() as base:
            inv = deepcopy(inv)
            inv['sermons'][0]['source_path'] = str(Path(base) / 'source.json')
            # Exact-path probing must never enter inference, migration or composition.
            with patch.object(TypeSafeBlockCache, 'assess_packs', side_effect=AssertionError('No inference')), patch.object(TypeSafeBlockCache, '_write_pack', side_effect=AssertionError('No writes')):
                checks = d.leaf_reuse_checks(inv, sources)
            self.assertEqual([], list(Path(base).iterdir()))
            self.assertEqual(1, len(checks))
            self.assertTrue(all(v['checked'] == 1 for v in checks[0]['packs'].values()))
            self.assertEqual([], checks[0]['matches'])

    def test_versioned_outputs_are_repeatable_and_cli_fingerprints_match(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from pastor_transcript_extractor.cli import app
        record = d.build(*fixture())
        with TemporaryDirectory() as base, patch.object(d, 'load', return_value=record), patch.object(d, 'build_paths', return_value=SimpleNamespace(evaluation=Path(base))):
            manifest, path = d.prepare()
            before = path.read_bytes()
            self.assertEqual((manifest, path), d.prepare())
            self.assertEqual(before, path.read_bytes())
            self.assertTrue((path.parent / 'review-v8.json').exists())
            self.assertTrue((path.parent / 'next-capability-v2.md').exists())
            self.assertTrue((path.parent / 'next-capability-v2.json').exists())
            generated = CliRunner().invoke(app, ['analysis', 'structure-readiness', '--segment-view', '--description', '--json'])
            checked = CliRunner().invoke(app, ['analysis', 'structure-readiness', '--segment-view', '--description', '--check-only', '--json'])
            self.assertEqual(0, generated.exit_code, generated.output)
            self.assertEqual(0, checked.exit_code, checked.output)
            self.assertEqual(json.loads(generated.output)['fingerprint'], json.loads(checked.output)['fingerprint'])

    def test_cli_description_check_only_cannot_write_and_rejects_execution_flags(self):
        from pastor_transcript_extractor.cli import app
        record = d.build(*fixture())
        with patch.object(d, 'load', return_value=record), patch.object(d, 'prepare', side_effect=AssertionError('No writes')):
            result = CliRunner().invoke(app, ['analysis', 'structure-readiness', '--segment-view', '--description', '--check-only', '--json'])
            self.assertEqual(0, result.exit_code, result.output)
        for flags in (['--description'], ['--description', '--segment-view', '--run-selection']):
            result = CliRunner().invoke(app, ['analysis', 'structure-readiness', *flags])
            self.assertEqual(2, result.exit_code, result.output)
