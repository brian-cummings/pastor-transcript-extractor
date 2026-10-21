from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from test_profile_description import fixture
from pastor_transcript_extractor import profile_description as description
from pastor_transcript_extractor import profile_evidence_supply as supply
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.sermon_classifier_typesafe import TypeSafeBlockCache
from pastor_transcript_extractor.sermon_leaf_packs import (
    LISTENER_DIRECTIVES, LISTENER_DIRECTIVES_V1, LISTENER_DIRECTIVE_REFINEMENT,
)


class SupplyTests(unittest.TestCase):
    def saved(self, base, spec, *, value=0.9, mutate=None):
        inv, sources = fixture()
        inv = deepcopy(inv)
        inv['sermons'][0]['source_path'] = str(Path(base) / 'source.json')
        check = supply.inspect(inv, sources)[0]
        attempt = next(a for a in check['attempts'] if a['pack'] == spec.version)
        cache = TypeSafeBlockCache(Path(base) / 'inference-cache', model=inv['sermons'][0]['model'])
        # Construct identity through the exact same public contracts, not inference.
        from pastor_transcript_extractor.sermon_classification import TranscriptBlock
        from pastor_transcript_extractor.sermon_topics import TopicBlockContext
        raw = sources[9]['classification']['search']['topic_analysis']['blocks'][0]
        context = TopicBlockContext(**raw['context'])
        block = TranscriptBlock(block_id=1, start_seconds=0, end_seconds=60,
            segment_indexes=[0], text=context.target_text)
        identity = cache._pack_identity({}, block, pack=spec.version, role_context=None, topic_context=context)
        payload = dict(identity=identity, answer=dict(resolved_model_id=cache.model,
            request_provenance={'source': 'saved-request'}, leaf_answer=dict(version=spec.version,
                context={**context.state_payload(), 'diagnostics': dict(context.diagnostics)},
                probabilities={leaf: value for leaf in spec.definitions})))
        if mutate:
            mutate(payload)
        path = Path(attempt['path']); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
        return seal(inv), sources, path

    def test_refinement_reused_without_full_pack_and_without_writes_or_inference(self):
        with TemporaryDirectory() as base:
            inv, sources, path = self.saved(base, LISTENER_DIRECTIVE_REFINEMENT)
            original = path.read_bytes()
            with patch.object(TypeSafeBlockCache, 'assess_packs', side_effect=AssertionError('inference')), patch.object(TypeSafeBlockCache, '_write_pack', side_effect=AssertionError('writes')), patch.object(TypeSafeBlockCache, 'compose_leaf_answer', side_effect=AssertionError('composition')):
                checks = description.leaf_reuse_checks(inv, sources)
                record = description.build(inv, sources, checks)
            self.assertEqual(original, path.read_bytes())
            leaf = next(o for o in record['observations'] if o['layer'] == 'cached_leaf')
            self.assertEqual([LISTENER_DIRECTIVES.version], leaf['current_question_matches'])
            self.assertEqual('measured_not_admitted', leaf['state'])
            self.assertFalse(any(c['rule'] == 'cached_leaf' for c in record['claims']))
            self.assertEqual(0, checks[0]['packs'][LISTENER_DIRECTIVES.version]['compatible'])
            gap = next(g for g in record['gaps'] if g['id'] == 'pastoral')
            self.assertTrue(gap['evidence_supply']['missing_fields'])
            self.assertTrue(gap['evidence_supply']['available_observation_ids'])

    def test_wrong_context_model_identity_and_provenance_rejected(self):
        for mutate in (
            lambda p: p['answer']['leaf_answer']['context'].update(target_text='different'),
            lambda p: p['answer'].update(resolved_model_id='different'),
            lambda p: p['identity'].update(inventory_digest='different'),
            lambda p: p['answer'].pop('request_provenance'),
        ):
            with self.subTest(mutate=mutate), TemporaryDirectory() as base:
                inv, sources, _ = self.saved(base, LISTENER_DIRECTIVE_REFINEMENT, mutate=mutate)
                check = supply.inspect(inv, sources)[0]
                self.assertEqual([], check['observations'])
                self.assertEqual(1, check['packs'][LISTENER_DIRECTIVE_REFINEMENT.version]['incompatible'])

    def test_historical_meaning_not_relabelled_and_conflicting_duplicates_visible(self):
        with TemporaryDirectory() as base:
            inv, sources, _ = self.saved(base, LISTENER_DIRECTIVES_V1, value=0.1)
            self.saved(base, LISTENER_DIRECTIVES, value=0.9)
            record = description.build(inv, sources, supply.inspect(inv, sources))
            leaves = [o for o in record['observations'] if o['layer'] == 'cached_leaf']
            old_serve = next(o for o in leaves if o['question_version'] == LISTENER_DIRECTIVES_V1.version and o['field'] == 'serve')
            self.assertEqual([], old_serve['current_question_matches'])
            trust = [o for o in leaves if o['field'] == 'trust']
            self.assertTrue(all(o['supply_conflict'] for o in trust))
            self.assertTrue(all(len(o['equivalent_question_observation_ids']) == 2 for o in trust))
            self.assertEqual(0, record['provider_requests'])

    def test_existing_claims_have_complete_materialized_supply_trace(self):
        record = description.build(*fixture(routed=True))
        for claim in record['claims']:
            self.assertEqual('supplied_existing_materialized_observations', claim['evidence_supply']['status'])
            self.assertTrue(claim['evidence_supply']['inspected_reuse'])
            self.assertEqual([], claim['evidence_supply']['missing_fields'])

    def test_matching_curated_bindings_preserve_original_G1_without_pilot_loader(self):
        from test_profile_proposition_review import fixture as reviewed_fixture
        from test_profile_binding_pilot import fixture as original_fixture
        from pastor_transcript_extractor import profile_binding_pilot as pilot
        from pastor_transcript_extractor import profile_proposition_review as review
        from pastor_transcript_extractor import evidence_pipeline_trace as trace
        baseline, authored = reviewed_fixture()
        record, definitions, contexts = original_fixture()
        real_definitions = json.loads(pilot.READINGS_PATH.read_text())
        for key in ('contract_path', 'contract_sha256', 'composer_path', 'composer_sha256'):
            definitions[key] = real_definitions[key]
        for case, compiled in zip(definitions['cases'], baseline['cases']):
            case['readings'] = compiled['readings']
        record['observations'] = [dict(id=case['evidence_id'], video_id=case['video_id'],
            block_id=case['block_id'], source_sha256=case['source_sha256'])
            for case in record['capability_review']['cases']]
        record['evidence_supply'] = {}
        record['gaps'] = []
        sources = {case['video_id']: dict(classification=dict(search=dict(topic_analysis=dict(
            blocks=[dict(block_id=case['block_id'], context=contexts[case['evidence_id']])]))))
            for case in record['capability_review']['cases']}
        authored['reused_contracts'] = {}
        with TemporaryDirectory() as base:
            original_path = Path(base) / 'original.json'
            original_path.write_text(json.dumps(definitions))
            authored['baseline_input_sha256'] = trace.digest(original_path)
            authored_path = Path(base) / 'authored.json'
            authored_path.write_text(json.dumps(authored))
            with patch.object(pilot, 'READINGS_PATH', original_path), patch.object(review, 'READINGS_PATH', authored_path), patch.object(pilot, 'load', side_effect=AssertionError('Recursive loader forbidden')):
                supply.reviewed_bindings(record, sources)
                actual = record['evidence_supply']['reviewed_bound_records']
                self.assertEqual(10, len(actual))
                expected = {r['id']: r['g1_record'] for c in baseline['cases'] for r in c['readings']}
                for value in actual:
                    self.assertEqual(expected[value['binding']['binding_id']], value['assurance_interpretation']['g1_record'])
                    self.assertEqual('source_reviewed_proposal_not_production_admission', value['status'])
                self.assertTrue(all(c['state'] == 'compatible_reviewed_proposals_reused' for c in record['evidence_supply']['reviewed_binding_checks']))
                # A context mutation with the same target must withhold that case.
                sources[0]['classification']['search']['topic_analysis']['blocks'][0]['context']['leading_context'] = 'changed'
                supply.reviewed_bindings(record, sources)
                self.assertEqual(2, len(record['evidence_supply']['reviewed_bound_records']))

    def test_exact_current_scripture_payload_exposed_under_original_meanings(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from pastor_transcript_extractor.models import SermonAnalysisEvidence, SermonAnalysisMeasurement
        from pastor_transcript_extractor.sermon_analysis import ANALYZER_KEY, ANALYZER_VERSION
        prepared = SimpleNamespace(input_fingerprint='input', source_content_sha256='source', source_path=Path('/identified.json'))
        run = SimpleNamespace(id=7, input_fingerprint='input', source_content_sha256='source',
            analyzer_key=ANALYZER_KEY, analyzer_version=ANALYZER_VERSION)
        database = Mock()
        database.list_sermon_analysis_evidence.return_value = [SermonAnalysisEvidence(
            id=1, analysis_run_id=7, evidence_kind='scripture_reference', evidence_key='reference',
            segment_index=0, start_seconds=0, end_seconds=5, char_start=0, char_end=8,
            excerpt='John 3:16', payload_json='{"canonical_reference":"John 3:16"}')]
        database.list_sermon_analysis_measurements.return_value = [SermonAnalysisMeasurement(
            id=2, analysis_run_id=7, metric_key='scripture_reference_mentions', value_json='1', unit='mentions')]
        output = supply.persisted_scripture(database, run, prepared)
        self.assertEqual('John 3:16', output['evidence'][0]['payload']['canonical_reference'])
        self.assertEqual(1, output['measurements'][0]['value'])
        self.assertIn('not cross-book reasoning', output['limit'])
        run.source_content_sha256 = 'changed'
        with self.assertRaisesRegex(ValueError, 'exact-current'):
            supply.persisted_scripture(database, run, prepared)
