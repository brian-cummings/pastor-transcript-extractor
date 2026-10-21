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
