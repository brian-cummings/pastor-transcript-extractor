from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from pastor_transcript_extractor.pastor_evidence import (
    compile_machine_binding, EvidenceArtifactStore, EvidencePolicy, REQUIRED_CHECKS, SampleSpec, SourceWindow,
)
from test_theological_binding import fixture


class EvidenceTests(unittest.TestCase):
    def window(self, text='αβ'):
        return SourceWindow('w', 1, 2, 'hash', 2, tuple(dict(block_id=i, target_text=t,
            start_seconds=i, end_seconds=i+1, segment_indexes=[i]) for i,t in [(1,text),(2,'next')]), 'control')

    def test_window_reversible_offsets(self):
        texts, mapping = self.window().target()
        self.assertEqual(texts['target_text'], 'αβ\nnext')
        self.assertEqual(mapping[1]['start'], 3)

    def test_policy_fail_closed(self):
        checks = {k:dict(resolved=True, probability=.9) for k in REQUIRED_CHECKS}
        row = dict(namespace='learning-demo-v3', production_admission='not_admitted', field_judgments=checks)
        self.assertTrue(EvidencePolicy().permits(row)[0])
        self.assertFalse(EvidencePolicy(require_production_admission=True).permits(row)[0])
        row['field_judgments']['voice']['probability'] = float('nan')
        self.assertFalse(EvidencePolicy().permits(row)[0])
        del row['field_judgments']['scope']
        self.assertFalse(EvidencePolicy().permits(row)[0])

    def test_machine_adapter_preserves_semantics_and_rejects_literal_failure(self):
        texts, row, _ = fixture()
        window = self.window(texts['target_text'])
        out = compile_machine_binding(window, row, model='test', prompt_digest='p', raw_response_ref='r')
        self.assertEqual(out['binding']['authorship'], 'machine_generated')
        self.assertEqual(out['production_admission'], 'not_admitted')
        self.assertEqual(out['binding']['voice'], row['voice'])
        self.assertEqual(out['binding']['conditions'], row['conditions'])
        self.assertFalse(EvidencePolicy().permits(out)[0])
        row['proposition']['span']['text'] = 'invented'
        with self.assertRaises(ValueError):
            compile_machine_binding(window, row, model='test', prompt_digest='p', raw_response_ref='r')

    def test_store_exact_immutable_and_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EvidenceArtifactStore(Path(directory))
            ref = store.write_immutable('a.json', {'a':1})
            self.assertEqual(store.read_exact('a.json', ref['sha256']), {'a':1})
            with self.assertRaises(ValueError): store.write_immutable('a.json', {'a':2})
            with self.assertRaises(ValueError): store.write_immutable('../escape.json', {})
        with self.assertRaises(ValueError): SampleSpec(1, (2,2), 'membership')

    def test_model_question_and_context_mutations_rejected(self):
        from pastor_transcript_extractor.pastor_evidence import ObservationEnvelope
        texts,row,_=fixture()
        envelope=compile_machine_binding(self.window(texts['target_text']),row,
            model='pinned',prompt_digest='question',raw_response_ref='receipt')
        for field in ('model','prompt_digest','source_refs'):
            mutated=deepcopy(envelope)
            if field=='source_refs': mutated[field][0]['target_sha256']='stale-context'
            else: mutated[field]='foreign'
            with self.assertRaisesRegex(ValueError,'identity changed'): ObservationEnvelope(mutated)
