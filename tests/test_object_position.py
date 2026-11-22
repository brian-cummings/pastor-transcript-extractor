import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.bound_claims.common import read_json, write_json
from pastor_transcript_extractor.object_position import components, contract, review, runner, sermon

try:
    from tests.bound_claims_support import CLEAN, DIRTY, METADATA, claim, stream_transport
except ImportError:
    from bound_claims_support import CLEAN, DIRTY, METADATA, claim, stream_transport

SPANS = [span for component in components.COMPONENTS for span in component['spans']]
OBJECT = 'the American experiment'


def leaf_table(extra=''):
    texts = [f'Opening words {i}. ' + ' '.join(SPANS[i::3]) + '.' for i in range(3)]
    texts[2] += extra
    blocks = [dict(coordinate=f'v1b{i}', text=text, start_seconds=60.0 * i) for i, text in enumerate(texts)]
    return dict(sermons=[dict(video_id=1, title='Sermon One', url='https://youtu.be/x', source_sha256='s' * 64, blocks=blocks)])


class ObjectPositionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.leaf, self.output = self.root / 'leaf.json', self.root / 'check'
        write_json(self.leaf, leaf_table())
        self.text = sermon.load(self.leaf, 1).text

    def send(self, claims, calls=None):
        return stream_transport({'v1': json.dumps(dict(claims=claims))}, calls)

    def run_check(self, claims, **kwargs):
        calls = kwargs.pop('calls', None)
        return runner.run(self.leaf, self.output, 1, OBJECT, transport=self.send(claims, calls), state=kwargs.pop('state', CLEAN), metadata=METADATA, **kwargs)

    def records(self, count=2):
        return [claim(SPANS[i], object=OBJECT) for i in range(count)]

    def test_check_only_reports_size_and_component_locations_and_writes_nothing(self):
        plan = runner.run(self.leaf, self.output, 1, OBJECT, check_only=True)
        self.assertTrue(plan['every_component_span_located_exactly_once'])
        self.assertEqual('0.2342912', plan['reserved_usd'])
        self.assertFalse(self.output.exists())

    def test_one_request_records_in_source_order_with_blocks_links_and_a_resolved_ledger(self):
        calls = []
        done = self.run_check(list(reversed(self.records(3))), calls=calls)
        self.assertEqual((1, 'ok', 3, None), (len(calls), done['status'], done['records'], done['stopped']))
        result = read_json(self.output / 'result.json')
        self.assertEqual([1, 2, 3], [r['number'] for r in result['records']])
        self.assertEqual(sorted(r['anchor']['start'] for r in result['records']), [r['anchor']['start'] for r in result['records']])
        self.assertTrue(all(r['coordinate'].startswith('v1b') and 'youtu.be/x?t=' in r['watch_url'] for r in result['records']))
        entry = next(iter(read_json(self.output / 'ledger.json')['entries'].values()))
        self.assertEqual('resolved', entry['status'])
        self.assertLessEqual(len(read_json(self.output / 'ledger.json')['entries']), 2)
        self.assertEqual(2, len(components.located(self.text)[1]))
        calls.clear()
        self.run_check(self.records(3), calls=calls)  # receipt exists: never resent
        self.assertEqual([], calls)

    def test_uncommitted_source_and_a_changed_object_are_refused_after_freeze(self):
        with self.assertRaises(ValueError):
            self.run_check(self.records(), state=DIRTY)
        self.run_check(self.records())
        with self.assertRaises(ValueError):
            runner.run(self.leaf, self.output, 1, 'some other object', transport=self.send([]), state=CLEAN, metadata=METADATA)

    def test_more_than_forty_records_is_a_stop_and_anchor_failures_are_kept_apart(self):
        many = [claim(SPANS[0], object=OBJECT, proposition=f'Point {i}.') for i in range(41)]
        self.assertIn('exceed the maximum of 40', self.run_check(many)['stopped'])
        self.output = self.root / 'second'
        done = self.run_check([claim('not in the sermon at all', object=OBJECT), *self.records(1)])
        self.assertEqual((1, 1), (done['records'], done['anchor_failures']))

    def test_ambiguous_component_span_is_refused(self):
        write_json(self.leaf, leaf_table(extra=' ' + SPANS[1]))
        with self.assertRaises(ValueError):
            self.run_check(self.records())

    def test_acceptance_passes_only_when_every_frozen_criterion_holds(self):
        self.run_check(self.records(3))
        result = read_json(self.output / 'result.json')
        full = dict(components={str(c['id']): [1] for c in components.COMPONENTS}, qualified=True,
                    records={str(i): dict(relevant=True, problem=False) for i in (1, 2, 3)})
        self.assertEqual('PASS', review.acceptance(result, full)['status'])
        for change in (dict(qualified=False), dict(components={**full['components'], '6': []}),
                       dict(records={**full['records'], '2': dict(relevant=False, problem=False), '3': dict(relevant=False, problem=False)}),
                       dict(records={**full['records'], '1': dict(relevant=True, problem=True)})):
            self.assertEqual('FAIL', review.acceptance(result, {**full, **change})['status'])

    def test_judging_loop_resumes_validates_and_feeds_the_report(self):
        self.run_check(self.records(2))
        with self.assertRaises(OSError):
            review.report(self.output)
        answers = iter(['x', '1', '2', 'n', '1,2', '3', '2', '1', 'n', 'y', 'q?', 'y n', 'y y'])
        screens = []
        saved = review.judge(self.output, lambda prompt: next(answers), screens.append)
        self.assertEqual({'1': [1], '2': [2], '3': [], '4': [1, 2], '5': [2], '6': [1], '7': []}, saved['components'])
        self.assertTrue(saved['qualified'])
        self.assertEqual({'1': dict(relevant=True, problem=False), '2': dict(relevant=True, problem=True)}, saved['records'])
        self.assertEqual(3, sum('Not understood' in text for text in screens))
        again = review.judge(self.output, lambda prompt: self.fail('resumed loop must not ask again'), lambda text: None)
        self.assertEqual(saved, again)
        outcome = review.report(self.output)
        self.assertEqual('FAIL', outcome['status'])
        self.assertEqual(['3', '7'], outcome['criteria']['1']['observed']['missing'])
        self.assertTrue((self.output / 'REPORT.md').exists())
        self.assertEqual('human', outcome['judged_by'])
        self.assertIn('Judgments by: human', (self.output / 'REPORT.md').read_text())

    def test_packet_lists_components_with_sources_and_records_without_model_identity(self):
        self.run_check(self.records(2))
        text = review.packet(read_json(self.output / 'result.json'), sermon.load(self.leaf, 1))
        for expected in ('Components (frozen)', 'youtu.be/x?t=', 'PROPOSITION:', 'ANCHOR: «'):
            self.assertIn(expected, text)
        for hidden in ('DeepSeek', 'Pro', 'reasoning'):
            self.assertNotIn(hidden, text)

    def test_instruction_and_request_use_the_frozen_contract(self):
        spec = runner.build_request(sermon.load(self.leaf, 1), OBJECT)
        self.assertEqual('object-position-v1-pro-stream-v1', spec.version)
        self.assertEqual(contract.SYSTEM_PROMPT, spec.body['messages'][0]['content'])
        self.assertEqual(json.dumps(dict(object=OBJECT, sermon_text=self.text), sort_keys=True, separators=(',', ':'), ensure_ascii=False),
                         spec.body['messages'][1]['content'])


if __name__ == '__main__':
    unittest.main()
