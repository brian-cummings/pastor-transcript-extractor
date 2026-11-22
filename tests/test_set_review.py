import json
import unittest

from pastor_transcript_extractor.bound_claims.common import digest, read_json, write_json
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.thought_units import leaf_evidence, public_set, set_review

try:
    from tests.bound_claims_support import CLEAN, DIRTY, METADATA, claim, stream_transport
    from tests.test_public_set import POLITICAL, Setup as SetSetup
except ImportError:
    from bound_claims_support import CLEAN, DIRTY, METADATA, claim, stream_transport
    from test_public_set import POLITICAL, Setup as SetSetup

ANCHOR = POLITICAL[:44]


def record(**changes):
    return claim(ANCHOR, area='public_life', object='the government', summary='The preacher says the government dominates the talk.', target='the government', **changes)


def reply(*records):
    return json.dumps(dict(records=list(records)))


class Setup(SetSetup):
    def setUp(self):
        super().setUp()
        out = public_set.set_dir(self.root)
        units = public_set.unit_records(public_set.sermon_blocks(read_json(self.source)))
        write_json(out / 'topics_v900.json', seal(dict(blocks=[dict(id=u['id'], block_id=0, signals={'T:society_public_life': 0.95}) for u in units])))
        write_json(out / 'leaves_v900.json', seal(dict(blocks=[dict(id='b0006', block_id=6, signals={'P:critical': 0.9, 'P:moral': 0.85})])))
        public_set.build_pairs(self.root)
        self.keys = ['v900-b0006-critical', 'v900-b0006-moral']

    def run_leaf(self, outputs, scope=leaf_evidence.DEVELOPMENT, calls=None, **kwargs):
        return leaf_evidence.run(self.root, transport=stream_transport(outputs, calls), state=kwargs.pop('state', CLEAN), metadata=METADATA,
                                 variant=kwargs.pop('variant', leaf_evidence.V2), scope=scope, **kwargs)


class ScopeTests(Setup):
    def test_the_development_half_runs_in_its_own_folder_and_ledger_with_the_frozen_plan_naming_its_scope(self):
        self.assertEqual(self.keys, [p['key'] for p in leaf_evidence.pair_inputs(self.root, leaf_evidence.DEVELOPMENT)])
        self.assertEqual([], leaf_evidence.pair_inputs(self.root, leaf_evidence.HELD_OUT))
        result = self.run_leaf({k: reply(record()) for k in self.keys})
        self.assertEqual((2, 2), (result['summary']['ok'], result['summary']['records']))
        folder = public_set.set_dir(self.root) / 'leaf-evidence-b2-development'
        plan = read_json(folder / 'plan.json')
        self.assertEqual(('development', '1.00', 60), (plan['scope'], plan['ceiling']['usd'], plan['ceiling']['attempts']))
        self.assertEqual(2, len(read_json(folder / 'ledger.json')['entries']))
        self.assertFalse((self.out / 'leaf-evidence-b2').exists())      # sermon 281's folder is untouched

    def test_a_dirty_tree_is_refused_before_any_request_and_check_only_sends_nothing(self):
        calls = []
        plan = leaf_evidence.run(self.root, check_only=True, variant=leaf_evidence.V2, scope=leaf_evidence.DEVELOPMENT, transport=stream_transport({}, calls))
        self.assertEqual((2, 2, []), (plan['pairs'], plan['requests_to_send'], calls))
        with self.assertRaises(ValueError):
            self.run_leaf({}, state=DIRTY)

    def test_a_changed_pair_file_is_refused_on_the_second_run(self):
        self.run_leaf({k: reply(record()) for k in self.keys})
        pairs = read_json(public_set.set_dir(self.root) / 'pairs.json')
        write_json(public_set.set_dir(self.root) / 'pairs.json', seal({k: v for k, v in pairs.items() if k != 'content_fingerprint'} | dict(note='changed')))
        with self.assertRaises(ValueError):
            self.run_leaf({k: reply(record()) for k in self.keys})


class VersionThreeTests(unittest.TestCase):
    def test_version_three_is_version_two_with_exactly_four_additions_and_its_own_folder(self):
        v2, v3 = leaf_evidence.SYSTEM_PROMPT_V2, leaf_evidence.SYSTEM_PROMPT_V3
        for added in ('find the words in `target_unit` that do what the `leaf` definition describes', 'Include every ground, reason, concession and limit',
                      '"X is antithetical to Y" is asserted, so affirm', 'a statement in `preceding_unit` or `following_unit` is never the anchor'):
            self.assertIn(added, v3)
            self.assertNotIn(added, v2)
        self.assertEqual(11, len([line for line in v3.splitlines() if line[:2].strip('.').isdigit() or line[:3].strip('.').isdigit()]))
        self.assertEqual(('v3', 'leaf-evidence-b3'), (leaf_evidence.V3.key, leaf_evidence.V3.directory))
        self.assertNotEqual(leaf_evidence.V2.prompt, leaf_evidence.V3.prompt)

    def test_a_revision_whose_old_text_is_missing_or_repeated_is_refused(self):
        with self.assertRaises(ValueError):
            leaf_evidence._revise('one two', (('three', 'x'),))
        with self.assertRaises(ValueError):
            leaf_evidence._revise('a a', (('a', 'x'),))


class MultiRecordTests(Setup):
    def test_version_four_allows_up_to_three_records_and_the_older_versions_still_allow_one(self):
        good = record()
        self.assertEqual(3, len(leaf_evidence.validate_records(dict(records=[good, good, good]), leaf_evidence.V4.max_records)))
        with self.assertRaises(leaf_evidence.SchemaError):
            leaf_evidence.validate_records(dict(records=[good] * 4), leaf_evidence.V4.max_records)
        with self.assertRaises(leaf_evidence.SchemaError):
            leaf_evidence.validate_records(dict(records=[good, good]), leaf_evidence.V3.max_records)
        self.assertEqual((1, 1, 3), (leaf_evidence.V2.max_records, leaf_evidence.V3.max_records, leaf_evidence.V4.max_records))
        self.assertIn('at most three', leaf_evidence.SYSTEM_PROMPT_V4)
        self.assertNotIn('at most one record', leaf_evidence.SYSTEM_PROMPT_V4)
        self.assertIn('Two records must state different points with different anchors', leaf_evidence.SYSTEM_PROMPT_V4)

    def test_a_three_leaf_cap_writes_its_own_pairs_file_and_leaves_the_two_leaf_pairs_alone(self):
        out = public_set.set_dir(self.root)
        write_json(out / 'leaves_v900.json', seal(dict(blocks=[dict(id='b0006', block_id=6, signals={'P:critical': 0.9, 'P:moral': 0.85, 'P:theological': 0.82, 'P:supportive': 0.81})])))
        two = public_set.build_pairs(self.root)
        three = public_set.build_pairs(self.root, 3)
        self.assertEqual((2, 3), (two['pairs'], three['pairs']))
        self.assertTrue((out / 'pairs.json').exists() and (out / 'pairs-top3.json').exists())
        self.assertEqual(2, len(public_set.half_pairs(self.root, 'development')))
        self.assertEqual(3, len(public_set.half_pairs(self.root, 'development', 'pairs-top3.json')))
        self.assertEqual(3, len(leaf_evidence.pair_inputs(self.root, leaf_evidence.DEVELOPMENT3)))
        self.assertEqual(2, len(leaf_evidence.pair_inputs(self.root, leaf_evidence.DEVELOPMENT)))

    def test_several_records_for_one_pair_are_queued_and_graded_one_by_one_with_a_padding_check(self):
        public_set.build_pairs(self.root, 3)
        first, second = POLITICAL[:44], POLITICAL[45:90]
        two = dict(records=[claim(first, area='public_life', object='the government', summary='The preacher says the government is talked about.', target='the government'),
                            claim(second, area='public_life', object='the election', summary='The preacher says the election is talked about.', target='the election',
                                  proposition='The election is discussed.', anchor_offsets=dict(start=45, end=90))])
        outputs = {k: json.dumps(two) for k in ('v900-b0006-critical', 'v900-b0006-moral')}
        leaf_evidence.run(self.root, transport=stream_transport(outputs), state=CLEAN, metadata=METADATA, variant=leaf_evidence.V4, scope=leaf_evidence.DEVELOPMENT3)
        single = {k: json.dumps(dict(records=[two['records'][0]])) for k in outputs}
        leaf_evidence.run(self.root, transport=stream_transport(single), state=CLEAN, metadata=METADATA, variant=leaf_evidence.V3, scope=leaf_evidence.DEVELOPMENT3)
        built = set_review.build_queue(self.root, 'development_top3')
        self.assertEqual(dict(v3=2, v4=4), built['records'])
        self.assertEqual(dict(v3=0, v4=2), built['pairs_with_several'])

        def answer(prompt):
            return 'a' if 'accept (a)' in prompt else 'y'
        set_review.judge(self.root, 'development_top3', 'claude', input_fn=answer, output_fn=lambda line: None)
        report = set_review.report(self.root, 'development_top3')
        self.assertEqual((None, 'v4', 'v3'), (report['passed'], report['primary'], report['reference']))
        self.assertEqual((4, 4, 2, 2), (report['tally']['v4']['records'], report['tally']['v4']['accepted'], report['tally']['v4']['pairs_with_several'], report['tally']['v4']['distinct_ok']))


class QueueTests(Setup):
    def test_development_review_labels_every_pair_blind_and_reports_defects(self):
        self.run_leaf({self.keys[0]: reply(record()), self.keys[1]: reply()})
        built = set_review.build_queue(self.root, 'development')
        self.assertEqual((2, 1), (built['pairs'], built['records']['v2']))
        queue = read_json(set_review.paths_for(self.root, 'development')['queue'])
        self.assertEqual(['none', 'record', 'summary'], sorted((i['kind'] for i in queue['items']), key={'none': 0, 'record': 1, 'summary': 2}.get))
        self.assertEqual('summary', queue['items'][-1]['kind'])                       # summaries come after the blind pass
        self.assertTrue(all('version' not in json.dumps(i) for i in queue['items']))

        def answer(prompt):
            return ('a' if 'accept (a)' in prompt else 'n' if 'Should this unit' in prompt else 'y')    # accept, fits; no record wanted; summary ok and framed
        lines = []
        set_review.judge(self.root, 'development', 'claude', input_fn=answer, output_fn=lines.append)
        self.assertEqual(0, set_review.progress(self.root, 'development')['remaining'])
        report = set_review.report(self.root, 'development')
        self.assertEqual(('v2', None, None), (report['primary'], report['reference'], report['passed']))
        self.assertEqual({'claude': 3}, report['labels_by'])
        self.assertEqual(2, report['tally']['v2']['pairs_correct'])
        self.assertEqual([], report['defects'])

    def test_unfinished_labels_block_the_report(self):
        self.run_leaf({k: reply(record()) for k in self.keys})
        set_review.build_queue(self.root, 'development')
        with self.assertRaises(ValueError):
            set_review.report(self.root, 'development')

    def test_the_held_out_sample_is_the_first_thirty_pairs_by_hash_of_the_key_and_the_same_for_every_version(self):
        pairs = [dict(video_id=2, key=f'k{i}') for i in range(50)]
        write_json(public_set.set_dir(self.root) / 'pairs.json', seal(dict(split=dict(development=[1], held_out=[2]), pairs=pairs)))
        sample = [p['key'] for p in set_review.reviewed_pairs(self.root, 'held_out')]
        self.assertEqual(30, len(sample))
        self.assertEqual(sorted((p['key'] for p in pairs), key=digest)[:30], sample)


class SpotCheckTests(unittest.TestCase):
    def test_the_spot_check_takes_every_distinct_item_and_fills_to_ten_by_hash(self):
        items = [dict(id=f'r{n}', kind='record') for n in range(30)] + [dict(id=f'd{n}', kind='distinct_points') for n in range(5)]
        chosen = set_review.spot_ids(dict(items=items))
        self.assertEqual(10, len(chosen))
        self.assertEqual({f'd{n}' for n in range(5)}, {i for i in chosen if i.startswith('d')})
        self.assertEqual(set(chosen), set(set_review.spot_ids(dict(items=list(reversed(items))))))        # independent of queue order


if __name__ == '__main__':
    unittest.main()
