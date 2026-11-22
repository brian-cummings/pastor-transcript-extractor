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


class ContextTests(unittest.TestCase):
    def pair(self, before, target, after):
        return dict(key='k', preceding_text='b' * before, text='t' * target, following_text='a' * after)

    def test_whole_neighbors_are_kept_only_while_the_three_units_fit_and_the_label_is_recorded(self):
        fit = leaf_evidence.fit_context
        self.assertEqual('full', fit(self.pair(1000, 2000, 1000))['context'])
        self.assertEqual('full', fit(self.pair(2000, 1000, 2000))['context'])       # exactly the budget
        kept = fit(self.pair(2500, 2000, 1000))
        self.assertEqual(('preceding_only', 2500, 0), (kept['context'], len(kept['preceding_text']), len(kept['following_text'])))
        kept = fit(self.pair(4000, 2000, 1000))
        self.assertEqual(('following_only', 0, 1000), (kept['context'], len(kept['preceding_text']), len(kept['following_text'])))
        kept = fit(self.pair(4000, 2000, 4000))
        self.assertEqual(('target_only', 2000), (kept['context'], len(kept['text'])))
        self.assertEqual(5266, len(fit(self.pair(9, 5266, 9))['text']))            # the target is never cut, even above the budget
        self.assertEqual('target_only', fit(self.pair(9, 5266, 9))['context'])
        self.assertEqual('full', fit(self.pair(0, 100, 0))['context'])


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


if __name__ == '__main__':
    unittest.main()
