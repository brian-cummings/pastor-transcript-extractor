import json
import unittest

from pastor_transcript_extractor.bound_claims.common import read_json
from pastor_transcript_extractor.thought_units import compare_review, leaf_evidence, unit_compare

try:
    from tests.bound_claims_support import CLEAN, DIRTY, METADATA, claim, stream_transport
    from tests.test_thought_unit_arms import Extracted
except ImportError:
    from bound_claims_support import CLEAN, DIRTY, METADATA, claim, stream_transport
    from test_thought_unit_arms import Extracted

ANCHOR = 'Second line sentence three goes here.'


def reply(anchor, summary='The preacher says a thing about the experiment.'):
    record = claim(anchor, area='public_life', object='the experiment', summary=summary, target='the experiment')
    return json.dumps(dict(records=[record]))


class MergeTests(unittest.TestCase):
    def test_the_same_leaf_with_overlapping_spans_is_one_passage_and_other_leaves_or_gaps_are_not(self):
        items = [dict(arm='b', unit='b1', leaf='P:critical', start=0, end=100), dict(arm='s', unit='s1', leaf='P:critical', start=50, end=120),
                 dict(arm='x', unit='x1', leaf='P:moral', start=60, end=90), dict(arm='b', unit='b2', leaf='P:critical', start=120, end=200)]
        groups = unit_compare.merge(items)
        self.assertEqual([['b1', 's1'], ['x1'], ['b2']], [[g['unit'] for g in group] for group in groups])

    def test_an_arm_uses_its_own_flagged_unit_with_the_largest_overlap_else_its_largest_overlapping_unit(self):
        units = [dict(id='u0', ordinal=0, start=0, end=40), dict(id='u1', ordinal=1, start=42, end=100), dict(id='u2', ordinal=2, start=102, end=140)]
        self.assertEqual(('u1', 'flagged'), (lambda r: (r[0]['id'], r[1]))(unit_compare.evidence_unit(units, ['u1'], 30, 110)))
        self.assertEqual(('u1', 'forced'), (lambda r: (r[0]['id'], r[1]))(unit_compare.evidence_unit(units, [], 30, 110)))
        self.assertEqual('u0', unit_compare.evidence_unit(units, ['u0', 'u2'], 0, 60)[0]['id'])
        with self.assertRaises(ValueError):
            unit_compare.evidence_unit(units, [], 500, 600)


class BuiltTests(Extracted):
    def setUp(self):
        super().setUp()
        self.built = unit_compare.build(self.root)

    def run_arm(self, arm, outputs=None, **kwargs):
        scope = leaf_evidence.COMPARE[arm]
        pairs = leaf_evidence.pair_inputs(self.root, scope)
        sent = outputs or {p['key']: reply(ANCHOR) if ANCHOR in p['text'] else json.dumps(dict(records=[])) for p in pairs}
        return leaf_evidence.run(self.root, transport=stream_transport(sent), state=kwargs.pop('state', CLEAN), metadata=METADATA, scope=scope, variant=leaf_evidence.V2, **kwargs)

    def test_every_arm_is_asked_about_every_passage_and_the_file_is_sealed_and_tied_to_the_units(self):
        clusters = unit_compare.load(self.root)['clusters']
        self.assertEqual(self.built['passages'], len(clusters))
        self.assertTrue(all(set(c['evidence']) == {'b', 's', 'x'} for c in clusters))
        for arm in unit_compare.ARMS:
            pairs = leaf_evidence.pair_inputs(self.root, leaf_evidence.COMPARE[arm])
            self.assertEqual(len({(c['evidence'][arm]['unit'], c['leaf']) for c in clusters}), len(pairs))
            self.assertTrue(all(p['key'].startswith(f'{arm}:') and p['text'] for p in pairs))
        path = unit_compare.clusters_path(self.root)
        path.write_text(path.read_text().replace('"p01"', '"p99"', 1))
        with self.assertRaises(ValueError):
            unit_compare.load(self.root)

    def test_an_arm_run_uses_its_own_folder_and_ledger_and_the_plan_names_the_scope(self):
        result = self.run_arm('s')
        self.assertEqual(result['summary']['ok'], len(leaf_evidence.pair_inputs(self.root, leaf_evidence.COMPARE['s'])))
        folder = unit_compare.compare_dir(self.root) / 'leaf-evidence-b2-s'
        plan = read_json(folder / 'plan.json')
        self.assertEqual(('compare_s', '1.00', 80), (plan['scope'], plan['ceiling']['usd'], plan['ceiling']['attempts']))
        with self.assertRaises(ValueError):
            self.run_arm('b', state=DIRTY)

    def test_the_queue_is_blind_to_arm_collapses_identical_records_and_the_report_reads_the_labels(self):
        for arm in unit_compare.ARMS:
            self.run_arm(arm)
        built = compare_review.build_queue(self.root)
        self.assertEqual(built['passages'], self.built['passages'])
        queue = read_json(compare_review.paths_for(self.root)['queue'])
        self.assertNotIn('arm', json.dumps(queue['items']).replace('"charm', ''))

        def answer(prompt):
            if prompt.startswith('Enter'):
                return ''
            return 'y' if '(y/n)' in prompt else 'tie'
        compare_review.judge(self.root, 'claude', input_fn=answer, output_fn=lambda line: None)
        self.assertEqual(0, compare_review.progress(self.root)['remaining'])
        report = compare_review.report(self.root)
        self.assertEqual(self.built['passages'], report['passages'])
        self.assertTrue(all(v['verdict'] == 'no demonstrated difference' for v in report['verdicts'].values()))
        self.assertEqual({'claude'}, set(report['labels_by']))


class EvaluateTests(unittest.TestCase):
    def passage(self, b, s, x, origin='flagged'):
        return dict(arm_option=dict(b=b, s=s, x=x), origin=dict(b=origin, s=origin, x=origin))

    def test_wins_losses_and_the_sign_test_decide_the_verdict_with_a_floor_on_decisive_comparisons(self):
        passages, decided = {}, {}
        for number in range(10):
            passages[f'p{number}'] = self.passage('A', 'B', None)
            decided[f'p{number}'] = dict(options=dict(A=dict(defensible=True, single=True), B=dict(defensible=True, single=True)), best='B')
        out = compare_review.evaluate(passages, decided, 10)
        self.assertEqual((10, 0), (out['pairwise_against_b']['s']['wins'], out['pairwise_against_b']['s']['losses']))
        self.assertEqual('better than time blocks', out['verdicts']['s']['verdict'])
        self.assertEqual(0.0009765625, compare_review.sign_test(10, 0))
        few = compare_review.evaluate({k: passages[k] for k in list(passages)[:3]}, decided, 3)
        self.assertEqual('no demonstrated difference', few['verdicts']['s']['verdict'])      # fewer than the floor

    def test_the_same_record_is_neither_a_win_nor_a_loss_and_a_worse_arm_is_reported(self):
        passages = {'same': self.passage('A', 'A', 'A')}
        decided = {'same': dict(options=dict(A=dict(defensible=True, single=False)), best=None)}
        out = compare_review.evaluate(passages, decided, 1)
        self.assertEqual(1, out['pairwise_against_b']['x']['same_record'])
        self.assertEqual((1, 0), (out['arms']['b']['records'], out['arms']['b']['good']))
        passages = {f'p{n}': self.passage('A', None, 'B') for n in range(9)}
        decided = {f'p{n}': dict(options=dict(A=dict(defensible=True, single=True), B=dict(defensible=True, single=True)), best='A') for n in range(9)}
        self.assertEqual('worse than time blocks', compare_review.evaluate(passages, decided, 9)['verdicts']['x']['verdict'])


if __name__ == '__main__':
    unittest.main()
