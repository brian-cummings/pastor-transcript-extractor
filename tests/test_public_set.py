from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.bound_claims.common import file_sha256, read_json, write_json
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.thought_units import arms, public_set, stage

try:
    from tests.bound_claims_support import CLEAN, DIRTY
except ImportError:
    from bound_claims_support import CLEAN, DIRTY

POLITICAL = 'The government and the president and the congress talk about the election and the constitution of America every single day.'
PLAIN = 'We read the story of the shepherd and the sheep and the lost coin in the Gospel this morning together.'


def proposed():
    texts = [PLAIN, POLITICAL, 'Please stand and sing the closing song with us now.', POLITICAL + ' ' + PLAIN]
    segments = [dict(start_seconds=10.0 * i, end_seconds=10.0 * i + 9, text=t, speaker_hint=None, label='sermon', confidence=0.9) for i, t in enumerate(texts)]
    blocks = [dict(block_id=i + 5, segment_indexes=[i], start_seconds=10.0 * i, end_seconds=10.0 * i + 9, text=t, normalization=dict(normalized_units=[])) for i, t in enumerate(texts)]
    labels = ['sermon', 'sermon', 'music', 'sermon']
    return dict(segments=segments, classification=dict(blocks=blocks, retained_segment_indexes=[0, 1, 3],
                                                     classifications=[dict(block_id=i + 5, label=label) for i, label in enumerate(labels)]))


class Setup(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.out = self.root / 'out'
        self.original = stage.paths
        stage.paths = lambda base: (self.root / 'leaf.json', self.root / 'slice.json', self.out)
        self.addCleanup(lambda: setattr(stage, 'paths', self.original))
        self.source = self.root / 'proposed.json'
        write_json(self.source, proposed())
        item = dict(video_id=900, youtube_video_id='abc', title='A sermon', url='https://youtu.be/abc', source_path=str(self.source), words=10000, hits=50, per_thousand=5.0,
                    source_sha256=file_sha256(self.source))
        write_json(public_set.set_dir(self.root) / 'candidates.json', seal(dict(version=public_set.VERSION, chosen=[item])))
        self.item = item


class FindTests(unittest.TestCase):
    def test_density_counts_the_frozen_vocabulary_per_thousand_words(self):
        measured = public_set.density(POLITICAL)
        self.assertEqual((20, 6), (measured['words'], measured['hits']))   # government, president, congress, election, constitution, america
        self.assertEqual(0, public_set.density(PLAIN)['hits'])

    def test_rank_orders_by_density_and_drops_short_sermons_unreadable_files_and_the_development_sermon(self):
        files = {'a': dict(segments=[dict(text=PLAIN * 500, label='sermon')], classification={}), 'b': dict(segments=[dict(text=(POLITICAL + ' ') * 400, label='sermon')], classification={}),
                 'c': dict(segments=[dict(text=POLITICAL, label='sermon')], classification={}), 'd': dict(segments=[dict(text=(POLITICAL + ' ') * 400, label='sermon')], classification={})}
        rows = [dict(video_id=1, youtube_video_id='x', title='plain', url='u', source_path='a'), dict(video_id=2, youtube_video_id='y', title='political', url='u', source_path='b'),
                dict(video_id=3, youtube_video_id='z', title='short', url='u', source_path='c'), dict(video_id=281, youtube_video_id='w', title='development', url='u', source_path='d'),
                dict(video_id=5, youtube_video_id='v', title='missing', url='u', source_path='missing')]
        ranked = public_set.rank(rows, lambda path: files[path])
        self.assertEqual([2, 1], [item['video_id'] for item in ranked])


class BlockTests(Setup):
    def test_units_are_the_sermon_labeled_saved_blocks_joined_by_a_blank_line_with_their_character_ranges(self):
        blocks = public_set.sermon_blocks(read_json(self.source))
        self.assertEqual([5, 6, 8], [b['block_id'] for b in blocks])        # the music block is not a sermon unit
        units = public_set.unit_records(blocks)
        text = public_set.sermon_layout(blocks)['text']
        self.assertTrue(all(text[u['start']:u['end']] == u['text'] for u in units))
        self.assertEqual(['b0005', 'b0006', 'b0008'], [u['id'] for u in units])

    def test_only_the_final_block_set_is_used_when_a_coarse_pass_precedes_it(self):
        def block(block_id, start, end, text, segment):
            return dict(block_id=block_id, segment_indexes=[segment], start_seconds=start, end_seconds=end, text=text, normalization=dict(normalized_units=[]))
        coarse = [block(0, 0.0, 300.0, 'coarse one ' * 30, 0), block(1, 300.0, 600.0, 'coarse two ' * 30, 1)]
        fine = [block(2, 0.0, 90.0, 'fine one ' * 10, 0), block(3, 90.0, 180.0, 'fine two ' * 10, 1), block(4, 180.0, 270.0, 'fine three ' * 10, 2)]
        for restart in (True, False):                 # numbering may restart or continue; time running backward also marks the new set
            second = [dict(b, block_id=b['block_id'] - 2) for b in fine] if restart else fine
            blocks = coarse + second
            labels = ['sermon', 'sermon', 'sermon', 'music', 'sermon']
            found = public_set.sermon_blocks(dict(classification=dict(blocks=blocks, classifications=[dict(block_id=b['block_id'], label=l) for b, l in zip(blocks, labels)])))
            self.assertEqual(['fine one ' * 10, 'fine three ' * 10], [b['text'] for b in found])
        with self.assertRaises(ValueError):
            public_set.sermon_blocks(dict(classification=dict(blocks=coarse, classifications=[dict(block_id=9, label='sermon')] * 2)))

    def test_check_only_plans_the_topic_step_without_sending_anything(self):
        plan = public_set.score_topics(self.root, check_only=True)
        self.assertEqual((1, 3), (plan['sermons'], plan['blocks']))
        self.assertEqual({900: 3}, plan['cache_misses'])
        self.assertFalse((public_set.set_dir(self.root) / 'topics_v900.json').exists())
        with self.assertRaises(ValueError):
            public_set.score_topics(self.root, state=DIRTY)

    def test_a_changed_source_after_the_set_was_chosen_is_refused(self):
        write_json(self.source, dict(proposed(), extra=1))
        with self.assertRaises(ValueError):
            public_set.load_candidates(self.root)

    def test_the_flag_rule_selects_pairs_with_neighbors_and_the_gate_chooses_which_blocks_get_the_leaf_pack(self):
        units = public_set.unit_records(public_set.sermon_blocks(read_json(self.source)))
        out = public_set.set_dir(self.root)
        topics = {u['id']: {arms.FLAG_TOPIC: score} for u, score in zip(units, (0.4, 0.95, 0.92))}
        write_json(out / 'topics_v900.json', seal(dict(blocks=[dict(id=k, block_id=0, signals=v) for k, v in topics.items()])))
        sermon = public_set._sermon(self.root, self.item)
        self.assertEqual([1, 2], public_set.gated_ordinals(sermon, public_set.topic_signals(self.root, 900)))
        write_json(out / 'leaves_v900.json', seal(dict(blocks=[
            dict(id='b0006', block_id=6, signals={'P:critical': 0.9, 'P:moral': 0.85, 'P:theological': 0.82}),
            dict(id='b0008', block_id=8, signals={'P:critical': 0.5, 'P:supportive': 0.7})])))
        built = public_set.build_pairs(self.root)
        self.assertEqual((2, 1), (built['pairs'], built['units_with_a_pair']))
        pairs = read_json(out / 'pairs.json')['pairs']
        self.assertEqual(['v900-b0006-critical', 'v900-b0006-moral'], [p['key'] for p in pairs])
        self.assertEqual(POLITICAL, pairs[0]['text'])
        self.assertEqual((PLAIN, POLITICAL + ' ' + PLAIN), (pairs[0]['preceding_text'], pairs[0]['following_text']))
        text = public_set.sermon_layout(public_set.sermon_blocks(read_json(self.source)))['text']
        self.assertEqual(POLITICAL, text[pairs[0]['unit_start']:pairs[0]['unit_start'] + len(POLITICAL)])

    def test_the_split_alternates_down_the_hash_order_and_flags_a_thin_half(self):
        split = public_set.split_sermons([1230, 1605, 548, 627, 487, 717], {1230: 21, 1605: 37, 548: 10, 627: 14, 487: 1, 717: 26})
        self.assertEqual([1230, 1605, 548, 627, 487, 717], split['order'])
        self.assertEqual(([1230, 548, 487], [1605, 627, 717]), (split['development'], split['held_out']))
        self.assertEqual(dict(development=32, held_out=77), split['pairs'])
        self.assertFalse(split['needs_decision'])
        self.assertTrue(public_set.split_sermons([1, 2], {1: 20, 2: 14})['needs_decision'])

    def test_a_half_returns_only_its_sermons_pairs(self):
        out = public_set.set_dir(self.root)
        write_json(out / 'pairs.json', seal(dict(split=dict(development=[1], held_out=[2]), pairs=[dict(video_id=1, key='a'), dict(video_id=2, key='b')])))
        self.assertEqual(['a'], [p['key'] for p in public_set.half_pairs(self.root, 'development')])
        self.assertEqual(['b'], [p['key'] for p in public_set.half_pairs(self.root, 'held_out')])
        with self.assertRaises(ValueError):
            public_set.half_pairs(self.root, 'other')

    def test_the_confirmatory_set_has_its_own_folder_ledger_and_whole_set_pairs(self):
        self.assertNotEqual(public_set.set_dir(self.root, 'v1'), public_set.set_dir(self.root, 'v2'))
        self.assertEqual('public-life-set-v2', public_set.set_dir(self.root, 'v2').name)
        self.assertNotEqual(public_set.ledger_for(self.root, 'v1').path if hasattr(public_set.ledger_for(self.root, 'v1'), 'path') else 1, 2)
        write_json(public_set.set_dir(self.root, 'v2') / 'pairs-top3.json', seal(dict(split=dict(development=[1], held_out=[2]), pairs=[dict(video_id=1, key='a'), dict(video_id=2, key='b')])))
        self.assertEqual(['a', 'b'], [p['key'] for p in public_set.half_pairs(self.root, 'all', 'pairs-top3.json', 'v2')])
        with self.assertRaises(FileNotFoundError):
            public_set.half_pairs(self.root, 'all', 'pairs-top3.json', 'v1')
        self.assertEqual((6, 0, 24, 6), (public_set.SETS['v1']['take'], public_set.SETS['v1']['skip'], public_set.SETS['v2']['take'], public_set.SETS['v2']['skip']))


if __name__ == '__main__':
    unittest.main()
