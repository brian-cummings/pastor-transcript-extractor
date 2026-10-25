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


class LiteralQuotationTests(unittest.TestCase):
    def test_unicode_and_cross_block_offsets_are_exact_and_input_immutable(self):
        from pastor_transcript_extractor.pastor_evidence import locate_literal_spans
        texts=dict(target_text='α😀 says:\nIf we trust, we remain. Unless we turn away.')
        quote=dict(source_field='target_text',text='α😀 says:\nIf we trust, we remain.')
        original=deepcopy(quote);located=locate_literal_spans(quote,texts)
        self.assertEqual(quote,original)
        self.assertEqual(located['start'],0)
        self.assertEqual(located['end'],len(quote['text']))
        self.assertEqual(texts['target_text'][located['start']:located['end']],quote['text'])
        shifted=locate_literal_spans(quote,dict(target_text='prefix '+texts['target_text']))
        self.assertEqual(shifted['start'],7)
        self.assertEqual(shifted['end']-located['end'],7)

    def test_ambiguous_overlapping_missing_normalized_and_empty_quotes_fail_closed(self):
        from pastor_transcript_extractor.pastor_evidence import locate_literal_spans
        for text,quote in [('echo echo','echo'),('aaa','aa'),('α β','α  β'),('é','é'),('text','')]:
            with self.subTest(text=text,quote=quote),self.assertRaises(ValueError):
                locate_literal_spans(dict(source_field='target_text',text=quote),dict(target_text=text))
        with self.assertRaises(ValueError):
            locate_literal_spans(dict(source_field='leading_context',text='text'),dict(target_text='text'))

    def test_complete_binding_retains_conditions_qualifications_and_voice(self):
        from pastor_transcript_extractor.pastor_evidence import locate_literal_spans
        text='Perhaps we remain, if we trust, unless we turn away.'
        _,row,_=fixture(text)
        def span(quote): return dict(source_field='target_text',text=quote)
        def quote_only(value):
            if isinstance(value,list): return [quote_only(v) for v in value]
            if not isinstance(value,dict): return value
            return {k:quote_only(v) for k,v in value.items() if not ('source_field' in value and k in ('start','end'))}
        row=quote_only(row)
        row['conditions']=[dict(kind='condition',span=span('if we trust'),rationale='Attached condition.'),
                           dict(kind='exception',span=span('unless we turn away'),rationale='Attached exception.')]
        row['epistemic_status'].update(value='expressed_uncertainty',evidence=[span('Perhaps')])
        block=dict(block_id=0,target_text=text,start_seconds=0,end_seconds=60,segment_indexes=[0])
        window=SourceWindow('synthetic',1,2,'source',0,(block,),'control')
        before=deepcopy(row)
        envelope=compile_machine_binding(window,row,model='test',prompt_digest='p',raw_response_ref='r',locate_quotes=True)
        self.assertEqual(row,before)
        self.assertEqual(envelope['binding']['conditions'],locate_literal_spans(row['conditions'],dict(target_text=text)))
        self.assertEqual(envelope['binding']['voice']['kind'],row['voice']['kind'])
        self.assertEqual(envelope['binding']['epistemic_status']['value'],'expressed_uncertainty')
        self.assertEqual(envelope['producer']['literal_locator'],'unique-verbatim-unicode-v1')
        self.assertEqual(envelope['production_admission'],'not_admitted')
