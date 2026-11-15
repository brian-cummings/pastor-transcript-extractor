import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.bound_claims import extract, review
from pastor_transcript_extractor.bound_claims.common import read_json, write_json
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger

try:
    from tests.bound_claims_support import CLEAN, block, claim, stream_transport
except ImportError:
    from bound_claims_support import CLEAN, block, claim, stream_transport


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / 'pilot'
        self.addCleanup(self.directory.cleanup)

    def produce(self, pro, flash, count=6, seed='a' * 64):
        write_json(self.root / 'slice.json', dict(profiles=[dict(profile_id=1, display_label='Pastor Sample')]))
        write_json(self.root / 'strata.json', dict(slice_sha256=seed, seed=seed, blocks=[block(i) for i in range(count)]))
        ledger = PilotLedger(self.root / 'ledger.json')
        for producer, outputs in (('pro', pro), ('flash', flash)):
            extract.run(self.root / 'strata.json', producer, ledger,
                        transport=stream_transport({f'v1b{i}': outputs.get(i, '{"claims":[]}') for i in range(count)}), state=CLEAN)

    def one(self, index, **changes):
        return json.dumps(dict(claims=[claim(f'We are saved by grace alone {index}.', **changes)]))

    def test_queue_is_blind_merged_across_producers_and_stably_shuffled(self):
        same = {i: self.one(i) for i in range(6)}
        self.produce(same, {**same, 0: self.one(0, polarity='reject')})
        queue = review.build_queue(self.root)
        self.assertEqual(7, queue['item_count'])  # six shared claims once + one flash-only variant
        dumped = json.dumps(queue)
        for hidden in ('producer', '"pro"', '"flash"', 'DeepSeek', 'reasoning'):
            self.assertNotIn(hidden, dumped)
        item = queue['items'][0]
        block_text = 'We are saved by grace alone {n}. Vote for the levy.'
        self.assertEqual(block_text.format(n=int(item['coordinate'][-1])), item['target_before'] + item['anchor'] + item['target_after'])
        self.assertEqual(queue, review.build_queue(self.root))
        self.assertEqual('Pastor Sample', item['pastor'])
        self.assertEqual(sorted(i['id'] for i in queue['items']), sorted({i['id'] for i in queue['items']}))
        first_ids = [i['id'] for i in queue['items'] if i['coordinate'] != 'v1b0']
        self.root = Path(self.directory.name) / 'other-seed'
        self.produce(same, same, seed='b' * 64)
        self.assertNotEqual(first_ids, [i['id'] for i in review.build_queue(self.root)['items']])

    def test_decisions_are_append_only_resumable_and_voidable(self):
        same = {i: self.one(i) for i in range(3)}
        self.produce(same, same, count=3)
        review.write_queue(self.root)
        queue = read_json(self.root / 'review.json')
        first, second = queue['items'][0]['id'], queue['items'][1]['id']
        review.record_decision(self.root, first, 'accept')
        review.record_decision(self.root, second, 'reject:voice')
        self.assertEqual({'accept', 'reject:voice'}, {r['decision'] for r in review.load_decisions(self.root).values()})
        self.assertEqual(1, review.progress(self.root)['remaining'])
        review.record_decision(self.root, second, 'void')
        self.assertEqual(2, review.progress(self.root)['remaining'])
        lines = (self.root / review.DECISIONS).read_text().splitlines()
        self.assertEqual(3, len(lines))
        self.assertTrue(all({'claim_fingerprint', 'decision', 'decided_at'} <= set(json.loads(line)) for line in lines))
        with self.assertRaises(ValueError):
            review.record_decision(self.root, first, 'reject:nonsense')

    def test_replay_is_idempotent_and_validates(self):
        same = {i: self.one(i) for i in range(3)}
        self.produce(same, same, count=3)
        queue = review._queue(self.root)
        mapping = {item['id']: 'accept' for item in queue['items']}
        mapping[queue['items'][0]['id']] = 'r:polarity'
        write_json(self.root / 'labels.json', mapping)
        first = review.replay(self.root, self.root / 'labels.json')
        self.assertEqual((3, 0), (first['written'], first['remaining']))
        again = review.replay(self.root, self.root / 'labels.json')
        self.assertEqual(0, again['written'])
        self.assertEqual('reject:polarity', review.load_decisions(self.root)[queue['items'][0]['id']]['decision'])
        write_json(self.root / 'bad.json', {'f' * 64: 'accept'})
        with self.assertRaises(ValueError):
            review.replay(self.root, self.root / 'bad.json')
        write_json(self.root / 'bad2.json', {queue['items'][0]['id']: 'maybe'})
        with self.assertRaises(ValueError):
            review.replay(self.root, self.root / 'bad2.json')

    def test_interactive_loop_resumes_and_supports_undo_and_quit(self):
        same = {i: self.one(i) for i in range(3)}
        self.produce(same, same, count=3)
        screens = []
        answers = iter(['a', 'x', 'r anchor', 'u', 'r:conditions', 'q'])
        done = review.interactive(self.root, lambda prompt: next(answers), screens.append)
        self.assertEqual((3, 2, 1), (done['items'], done['decided'], done['remaining']))
        decisions = [r['decision'] for r in sorted(review.load_decisions(self.root).values(), key=lambda r: r['decided_at'])]
        self.assertEqual(['accept', 'reject:conditions'], decisions)
        self.assertTrue(any('Not understood' in s for s in screens))
        self.assertTrue(any('«We are saved by grace alone' in s and 'youtu.be' in s and 'Pastor Sample' in s for s in screens))
        resumed = iter(['a'])
        finished = review.interactive(self.root, lambda prompt: next(resumed), lambda s: None)
        self.assertEqual(0, finished['remaining'])

    def test_decision_parser(self):
        self.assertEqual('accept', review.parse_decision('A'))
        self.assertEqual('reject', review.parse_decision('reject'))
        self.assertEqual('reject:adoption', review.parse_decision('r adoption'))
        self.assertEqual('reject:qualifications', review.parse_decision('reject:qualifications'))
        self.assertIsNone(review.parse_decision('reject:colour'))
        self.assertIsNone(review.parse_decision('accept:voice'))

    def test_both_producers_are_required(self):
        write_json(self.root / 'slice.json', dict(profiles=[]))
        write_json(self.root / 'strata.json', dict(slice_sha256='a', seed='a', blocks=[]))
        with self.assertRaises(ValueError):
            review.build_queue(self.root)


if __name__ == '__main__':
    unittest.main()
