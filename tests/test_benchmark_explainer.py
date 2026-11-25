import unittest

from pastor_transcript_extractor.benchmark_explainer import free, render, values


def _sermon(video, pastor):
    return {'video_id': video, 'pastor': pastor, 'youtube_video_id': f'y{video}'}


def _blocks(story_share, n=50):
    hits = int(story_share * n)
    return {'blocks': [{'start_seconds': i * 90.0, 'text': f'block {i} text',
                        'signals': {'M:personal_testimony': 0.9 if i < hits else 0.1,
                                    'T:salvation_gospel': 0.6, 'S:assurance_security': 0.85 if i % 2 else 0.2}}
                       for i in range(n)]}


def _corpus():
    """Ten ordinary pastors with little testimony; the benchmark 'b65' tells personal stories a lot."""
    sermons, scored, measured = [], {}, {}
    video = 0
    for pastor_index in range(10):
        pastor = f'p{pastor_index}'
        for _ in range(4):
            video += 1
            sermons.append(_sermon(video, pastor))
            scored[video] = _blocks(0.05 + 0.02 * pastor_index)
            measured[video] = {name: 1.0 + 0.1 * pastor_index for name in free.DIMENSIONS}
    for _ in range(6):
        video += 1
        sermons.append(_sermon(video, 'b65'))
        scored[video] = _blocks(0.5)
        measured[video] = {name: 1.5 for name in free.DIMENSIONS}
    return sermons, scored, measured


class BenchmarkExplainerTests(unittest.TestCase):
    def setUp(self):
        self.sermons, self.scored, self.measured = _corpus()
        self.dimensions = values.jev_dimensions(self.scored.values())
        self.table = values.pastor_values(self.scored, self.measured, self.sermons, self.dimensions)

    def test_jev_value_is_share_of_blocks_at_the_floor_not_a_probability(self):
        self.assertAlmostEqual(self.table['b65']['M:personal_testimony']['value'], 0.5)
        self.assertEqual(self.table["b65"]["M:personal_testimony"]["n"], 300)
        # topic floor is 0.55, so a 0.6 topic answer counts
        self.assertEqual(self.table['p0']['T:salvation_gospel']['value'], 1.0)

    def test_scale_falls_back_when_mad_is_zero(self):
        median, spread = values.scale([0.0] * 8 + [1.0, 2.0])
        self.assertEqual(median, 0.0)
        self.assertAlmostEqual(spread, 1.2533 * 0.3)
        self.assertEqual(values.scale([1.0] * 5), (1.0, 0.0))

    def test_explain_offers_only_distinctive_and_stable_dimensions_with_evidence(self):
        result = values.explain('b65', self.sermons, self.table, self.scored, self.measured, self.dimensions)
        explained = {row['dimension']: row for row in result['explained']}
        self.assertIn('M:personal_testimony', explained)
        row = explained['M:personal_testimony']
        self.assertGreater(row['z'], values.DISTINCT_Z)
        self.assertTrue(all(z > values.STABLE_Z for z in row['z_halves']))
        evidence = row['evidence']
        self.assertEqual(len(evidence), 2)
        self.assertNotEqual(evidence[0]['video_id'], evidence[1]['video_id'])
        # every pastor answers the topic identically, so it cannot be distinctive
        self.assertNotIn('T:salvation_gospel', explained)

    def test_rank_puts_the_most_similar_pastor_first(self):
        by_pastor = {}
        for sermon in self.sermons:
            by_pastor.setdefault(sermon['pastor'], []).append(sermon['video_id'])
        ranked = values.rank('b65', ['M:personal_testimony'], self.table, by_pastor, self.scored, self.measured)
        self.assertEqual(ranked[0]['pastor'], 'p9')
        self.assertIn('M:personal_testimony', ranked[0]['evidence'])
        self.assertNotIn('b65', [r['pastor'] for r in ranked])

    def test_verdicts_apply_the_pass_marks(self):
        explanations = {'b65': {'explained': [{'dimension': f'M:d{i}'} for i in range(5)]}}
        marks = {'b65/M:d0': 'true', 'b65/M:d1': 'true', 'b65/M:d2': 'true', 'b65/M:d3': 'not_true', 'b65/M:d4': 'cannot_tell'}
        ranks = {'b65': {'chosen': ['M:d0'], 'judgments': {f'p{i}': 'supported' for i in range(4)} | {'p9': 'not_supported'},
                         'shortlist': []}}
        result = render.verdicts(explanations, marks, ranks, None,
                                 {'failed_calls': 0, 'incomplete_sermons': [], 'ledger': {}})
        self.assertTrue(result['benchmarks']['b65']['e1']['passed'])     # 3 of 4 judged, one not true
        self.assertTrue(result['benchmarks']['b65']['e2']['passed'])     # 4 of 5 supported
        marks['b65/M:d2'] = 'not_true'
        result = render.verdicts(explanations, marks, ranks, None,
                                 {'failed_calls': 0, 'incomplete_sermons': [], 'ledger': {}})
        self.assertFalse(result['benchmarks']['b65']['e1']['passed'])

    def test_labels_and_values_read_plainly(self):
        self.assertEqual(render.label('M:personal_testimony'), 'Uses: personal testimony')
        self.assertEqual(render.show('M:personal_testimony', 0.5), '50.0% of preaching blocks')
        self.assertEqual(render.show('F:sermon_minutes', 41.0), '41.00 minutes')


if __name__ == '__main__':
    unittest.main()


class SermonReviewTests(unittest.TestCase):
    def test_proposal_follows_the_speakers_named_in_the_title(self):
        from pastor_transcript_extractor.benchmark_explainer.runner import propose
        self.assertEqual(propose('Sanctuary Defiled | DWELL S09 [Ty Gibson]', 'Ty Gibson')[0], 'keep')
        self.assertEqual(propose('Overthinking | S2 E01 [Ty Gibson, David Asscherick, Angelo Grasso]', 'Ty Gibson')[0], 'drop')
        self.assertEqual(propose('Home at Last | DWELL S10 [David Asscherick]', 'Ty Gibson')[0], 'drop')
        self.assertEqual(propose('Politics at the End  |  The End.', 'Ty Gibson')[0], 'keep')

    def test_all_reviews_every_recording_and_enter_accepts_the_proposal(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from pastor_transcript_extractor.benchmark_explainer import runner
        from pastor_transcript_extractor.bound_claims.common import read_json, write_json
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            checks = [dict(video_id=v, pastor='b65', title=t, url='u', own_rank=1.0, flagged=False, nearest=['b65'])
                      for v, t in ((1, 'A [Ty Gibson]'), (2, 'B [Ty Gibson, David Asscherick]'), (3, 'Year in review'))]
            write_json(out / 'sermon_check.json', dict(checks=checks))
            answers, opened = iter(['', '', 'd']), []
            with mock.patch.object(runner, '_paths', return_value=(out, out, out / 'db')), \
                    mock.patch.object(runner.data, 'pastor_names', return_value={'b65': 'Ty Gibson'}):
                self.assertEqual(runner.sermon_review(out, echo=lambda *_: None)['dropped'], 0)  # nothing flagged
                result = runner.sermon_review(out, ask=lambda _: next(answers), echo=lambda *_: None, all_recordings=True,
                                              open_url=opened.append)
            self.assertEqual(result['dropped_videos'], [2, 3])
            self.assertEqual(len(opened), 3)
            self.assertEqual(read_json(out / 'sermon_decisions.json'), {'1': 'keep', '2': 'drop', '3': 'drop'})

    def test_decide_files_a_recording_under_the_other_benchmark(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from pastor_transcript_extractor.benchmark_explainer import runner
        from pastor_transcript_extractor.bound_claims.common import write_json
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_json(out / 'sermons.json', [_sermon(v, p) for v, p in ((1, 'b65'), (2, 'b65'), (3, 'b66'))])
            write_json(out / 'sermon_check.json', dict(checks=[dict(video_id=v, flagged=False) for v in (1, 2, 3)]))
            with mock.patch.object(runner, '_paths', return_value=(out, out, out / 'db')):
                runner.sermon_decide(out, [2], 'file:66')
                runner.sermon_decide(out, [3], 'drop')
                with self.assertRaises(ValueError):
                    runner.sermon_decide(out, [1], 'file:99')
                with self.assertRaises(ValueError):
                    runner.sermon_decide(out, [7], 'drop')
            active = runner._active_sermons(out)
            self.assertEqual([(s['video_id'], s['pastor']) for s in active], [(1, 'b65'), (2, 'b66')])


class WideningTests(unittest.TestCase):
    def test_added_rounds_have_their_own_files_and_ceiling_and_leave_the_approved_run_alone(self):
        import tempfile
        from decimal import Decimal
        from pathlib import Path
        from unittest import mock
        from pastor_transcript_extractor.benchmark_explainer import score
        from pastor_transcript_extractor.bound_claims.common import read_json, write_json
        plan = dict(sermons=1, blocks=1, cache_misses={}, reusable_saved_answers=0, worst_case_requests=3,
                    worst_case_reserved_usd='0', ceiling_usd='15.00')
        fake = lambda out, sermon, client, failures, echo: dict(video_id=sermon['video_id'], pastor=sermon['pastor'], calls=1, blocks=[])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_json(out / 'score.json', {'approved': True})
            with mock.patch.object(score, 'census', return_value=dict(plan)), mock.patch.object(score, 'score_sermon', fake):
                first = score.run_round(out, out, [_sermon(1, 'b65')], ceiling_usd=Decimal('2.00'),
                                        client_factory=lambda model: None, echo=lambda *_: None)
                second = score.run_round(out, out, [_sermon(2, 'b66')], ceiling_usd=Decimal('2.00'),
                                         client_factory=lambda model: None, echo=lambda *_: None)
            self.assertEqual(read_json(out / 'score.json'), {'approved': True})
            self.assertEqual(first['incomplete_sermons'], [])
            round_1, round_2 = out / 'added-rounds' / 'round-1', out / 'added-rounds' / 'round-2'
            self.assertEqual(read_json(round_1 / 'score_plan.json')['ceiling_usd'], '2.00')
            self.assertEqual(read_json(round_1 / 'score_plan.json')['video_ids'], [1])
            self.assertEqual(read_json(round_2 / 'score_plan.json')['video_ids'], [2])
            self.assertTrue((round_2 / 'score.json').exists() and (out / 'signals' / 'v2.json').exists())
            self.assertEqual(second['plan']['invocations'], 1)

    def test_add_sermons_appends_only_new_benchmark_recordings(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from pastor_transcript_extractor.benchmark_explainer import runner
        from pastor_transcript_extractor.bound_claims.common import read_json, write_json
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            before = [dict(_sermon(1, 'p1'), extraction_path='x'), dict(_sermon(2, 'b65'), extraction_path='x')]
            write_json(out / 'sermons.json', before)
            write_json(out / 'measured.json', {'1': {}, '2': {}})
            write_json(out / 'sermon_check.json', dict(checks=[dict(video_id=2, pastor='b65', flagged=False)],
                                                       excluded_without_sermon_window=[]))
            now = before + [dict(_sermon(3, 'b66'), extraction_path='x')]
            check = lambda sermons, targets, database, echo: [dict(video_id=t['video_id'], pastor=t['pastor'], title='t',
                                                                   url='u', own_rank=1.0, flagged=False, nearest=[]) for t in targets]
            with mock.patch.object(runner, '_paths', return_value=(out, out, out / 'db')), \
                    mock.patch.object(runner.data, 'load', return_value=[]), \
                    mock.patch.object(runner.data, 'as_dicts', return_value=now), \
                    mock.patch.object(runner, '_measure', return_value={'m': 1}), \
                    mock.patch.object(runner, '_checks', check):
                result = runner.add_sermons(out, echo=lambda *_: None)
                again = runner.add_sermons(out, echo=lambda *_: None)
            self.assertEqual([a['video_id'] for a in result['added']], [3])
            self.assertEqual(again['added'], [])
            self.assertEqual([s['video_id'] for s in read_json(out / 'sermons.json')], [1, 2, 3])
            self.assertEqual(read_json(out / 'measured.json')['3'], {'m': 1})


class BreadthTests(unittest.TestCase):
    def test_breadth_separates_a_pattern_from_a_few_sermons(self):
        def sermon(hits, n=20):
            return {'blocks': [{'signals': {'M:personal_testimony': 0.9 if i < hits else 0.1}} for i in range(n)]}
        row = {'dimension': 'M:personal_testimony', 'z': 2.0, 'pool_median': 0.05}
        spread = {v: sermon(3) for v in range(1, 9)}
        lumped = {1: sermon(18), 2: sermon(17), 3: sermon(16), **{v: sermon(0) for v in range(4, 9)}}
        self.assertTrue(values.breadth(row, list(spread), spread, {})['pattern'])
        result = values.breadth(row, list(lumped), lumped, {})
        self.assertFalse(result['pattern'])
        self.assertEqual(result['on_his_side'], 3)
