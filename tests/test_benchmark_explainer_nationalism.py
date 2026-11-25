import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pastor_transcript_extractor.benchmark_explainer import nationalism, score
from pastor_transcript_extractor.bound_claims.common import read_json, write_json
from pastor_transcript_extractor.bound_claims.leaf_pass import PACKS, SIGNAL_COUNTS
from pastor_transcript_extractor.sermon_classification import TranscriptBlock
from pastor_transcript_extractor.sermon_leaf_packs import CHRISTIAN_NATIONALISM, LEAF_PACKS

LEAVES = ('chosen_nation', 'enforced_faith', 'partisan_faithfulness', 'christian_dominance')


def _answer(value):
    return SimpleNamespace(leaf_answers={nationalism.PACK: {'probabilities': {leaf: value for leaf in LEAVES}}})


class FakeCache:
    def __init__(self, asked, value):
        self.asked, self.value = asked, value

    def _pack_path(self, pack, identity):
        return Path('/nonexistent') / pack

    def assess_packs(self, client, context, blocks, *, requested_packs, topic_contexts):
        assert requested_packs == frozenset({nationalism.PACK})
        self.asked.extend(b.block_id for b in blocks)
        return {b.block_id: _answer(self.value) for b in blocks}


def _signals(video, topic_scores):
    return dict(video_id=video, pastor='p1', calls=1,
                blocks=[dict(ordinal=i, block_id=i, start_seconds=60.0 * i, end_seconds=60.0 * i + 60, text=f'text {i}',
                             signals={'T:society_public_life': t}) for i, t in enumerate(topic_scores)])


class PackTests(unittest.TestCase):
    def test_pack_has_the_four_approved_indicators_and_is_registered(self):
        self.assertEqual(tuple(CHRISTIAN_NATIONALISM.definitions), LEAVES)
        self.assertIs(LEAF_PACKS[CHRISTIAN_NATIONALISM.version], CHRISTIAN_NATIONALISM)
        self.assertEqual(PACKS['N'][0], CHRISTIAN_NATIONALISM.version)
        self.assertEqual(SIGNAL_COUNTS['N'], 4)
        questions = CHRISTIAN_NATIONALISM.questions(0)
        self.assertEqual(len(questions), 4)
        self.assertIn('Adventist prophetic warnings', questions['christian_nationalism_0_enforced_faith']['criteria']['false'])

    def test_probe_file_covers_every_leaf_and_the_critical_adventist_cases(self):
        probes = json.loads(nationalism.PROBE_PATH.read_text())
        expected = {leaf for p in probes for leaf in p['expected_positive_leaves']}
        self.assertEqual(expected, set(LEAVES))
        self.assertTrue(any('Revelation 13' in p['target_text'] and p['critical'] for p in probes))
        self.assertTrue(all(not p['expected_positive_leaves'] for p in probes if p['critical']))


class ProbeJudgeTests(unittest.TestCase):
    probes = [dict(target_text='a', expected_positive_leaves=['chosen_nation'], critical=False, reason='r'),
              dict(target_text='b', expected_positive_leaves=[], critical=True, reason='r'),
              dict(target_text='c', expected_positive_leaves=[], critical=False, reason='r')]

    def _probabilities(self, a, b, c):
        return {0: {**{l: 0.0 for l in LEAVES}, 'chosen_nation': a}, 1: {**{l: 0.0 for l in LEAVES}, 'enforced_faith': b},
                2: {**{l: 0.0 for l in LEAVES}, 'partisan_faithfulness': c}}

    def test_one_ordinary_miss_passes(self):
        result = nationalism.judge_probes(self.probes, self._probabilities(0.9, 0.1, 0.7))
        self.assertTrue(result['passed'])
        self.assertEqual(result['misses'], 1)

    def test_a_critical_miss_fails(self):
        result = nationalism.judge_probes(self.probes, self._probabilities(0.9, 0.6, 0.1))
        self.assertFalse(result['passed'])
        self.assertEqual(result['critical_misses'], 1)


class RoundTests(unittest.TestCase):
    def _setup(self, out):
        write_json(out / 'signals' / 'v1.json', _signals(1, [0.9, 0.1, 0.6]))
        write_json(out / 'signals' / 'v2.json', _signals(2, [0.0, 0.2]))
        write_json(out / score.NATIONALISM_DIR / 'probe' / 'result.json', {'passed': True})
        blocks = [TranscriptBlock(block_id=i, segment_indexes=[i], start_seconds=0, end_seconds=1, text=f'text {i}') for i in range(3)]
        return [dict(video_id=1, pastor='p1', extraction_path='x'), dict(video_id=2, pastor='p2', extraction_path='y')], blocks

    def test_only_public_life_blocks_are_asked_and_readers_change_only_on_accept(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            sermons, blocks = self._setup(out)
            asked = []
            before = read_json(out / 'signals' / 'v1.json')
            with mock.patch.object(score, 'sermon_blocks', return_value=(None, blocks, {b.block_id: None for b in blocks})), \
                 mock.patch.object(score, 'cache_for', return_value=FakeCache(asked, 0.7)), \
                 mock.patch.object(nationalism.arms, '_identities', return_value=[{}]):
                census = nationalism.add(out, sermons, ceiling_usd=Decimal('0.50'), check_only=True)
                self.assertEqual((census['routed_blocks'], census['sermons_with_routed_blocks']), (2, 1))
                result = nationalism.add(out, sermons, ceiling_usd=Decimal('0.50'), client_factory=lambda m: None,
                                         echo=lambda *_: None)
            self.assertEqual(sorted(asked), [0, 2])
            self.assertEqual(result['incomplete_sermons'], [])
            self.assertEqual(read_json(out / 'signals' / 'v1.json'), before)
            self.assertIn('2 of 2 public-life blocks', (out / score.NATIONALISM_DIR / 'round' / 'REVIEW.md').read_text())
            self.assertEqual(score.order(out), 'THLMSP')
            with self.assertRaises(ValueError):   # no more scoring while the review awaits a decision
                score._run(out, out, [], files=out / 'r', ceiling_usd=Decimal('1'), client_factory=None, state=None, echo=print)
            nationalism.decide(out, decision='accept', note='real cases')
            merged = read_json(out / 'signals' / 'v1.json')
            self.assertEqual(merged['blocks'][0]['signals']['N:chosen_nation'], 0.7)
            self.assertNotIn('N:chosen_nation', merged['blocks'][1]['signals'])
            self.assertEqual(score.order(out), 'THLMSPN')

    def test_reject_leaves_signals_alone_and_add_needs_a_passed_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            sermons, blocks = self._setup(out)
            write_json(out / score.NATIONALISM_DIR / 'probe' / 'result.json', {'passed': False})
            with self.assertRaises(ValueError):
                nationalism.add(out, sermons, ceiling_usd=Decimal('0.50'))
            write_json(out / score.NATIONALISM_DIR / 'probe' / 'result.json', {'passed': True})
            before = read_json(out / 'signals' / 'v1.json')
            with mock.patch.object(score, 'sermon_blocks', return_value=(None, blocks, {b.block_id: None for b in blocks})), \
                 mock.patch.object(score, 'cache_for', return_value=FakeCache([], 0.9)), \
                 mock.patch.object(nationalism.arms, '_identities', return_value=[{}]):
                nationalism.add(out, sermons, ceiling_usd=Decimal('0.50'), client_factory=lambda m: None, echo=lambda *_: None)
            nationalism.decide(out, decision='reject', note='false matches')
            self.assertEqual(read_json(out / 'signals' / 'v1.json'), before)
            self.assertEqual(score.order(out), 'THLMSP')


if __name__ == '__main__':
    unittest.main()
