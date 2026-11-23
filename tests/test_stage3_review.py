import unittest

from pastor_transcript_extractor.thought_units import stage3_review as review


def cell(level, video=1, cut=False, **extra):
    base = dict(outcome=review.OUTCOME[level], level=level, cut=cut, video=video)
    return dict(base, **extra)


class ReadingTests(unittest.TestCase):
    def test_sign_test_is_one_sided_and_matches_the_hand_count(self):
        self.assertAlmostEqual(0.0577, review.sign_p(14, 6), 3)      # 14 of 20 discordant blocks
        self.assertAlmostEqual(0.1316, review.sign_p(13, 7), 3)      # 13 of 20 does not reach 0.10, as 28.3 and 28.8 say
        self.assertIsNone(review.sign_p(0, 0))
        self.assertEqual(1.0, review.sign_p(0, 5))

    def test_a_block_is_scored_by_the_mean_of_its_pairs_and_ties_are_left_out(self):
        outcomes = dict(a={'v1-b1-x': cell('complete'), 'v1-b1-y': cell('wrong'), 'v1-b2-x': cell('complete'), 'v1-b3-x': cell('accurate_incomplete')},
                        b={'v1-b1-x': cell('accurate_incomplete'), 'v1-b1-y': cell('complete'), 'v1-b2-x': cell('complete'), 'v1-b3-x': cell('none')})
        result = review.compare(outcomes, 'a', 'b')
        self.assertEqual((4, 3), (result['pairs'], result['blocks']))
        self.assertEqual((1, 1, 1), (result['wins'], result['losses'], result['ties']))   # block 1: (3+0)-(2+3) is -1 over 2 pairs, a loss; block 3: 2 against 1, a win; block 2 ties
        self.assertAlmostEqual(0.0, result['mean_difference'])                           # block differences -1, 0 and +1

    def test_wrong_is_worse_than_no_record_and_a_missing_request_is_left_out(self):
        table = dict(u={'v1-b1-x': dict(state='missing', claim=None, cut=False, video=1), 'v1-b2-x': dict(state='no_record', claim=None, cut=True, video=1)})
        outcomes = review.pair_outcomes(table, {})
        self.assertEqual({'v1-b2-x'}, set(outcomes['u']))
        self.assertEqual(1, outcomes['u']['v1-b2-x']['outcome'])
        self.assertLess(review.OUTCOME['wrong'], review.OUTCOME['none'])

    def test_verdict_needs_enough_discordant_blocks_and_every_comparison_to_agree(self):
        def comp(wins, losses):
            return dict(wins=wins, losses=losses, p_first_better=review.sign_p(wins, losses), p_second_better=review.sign_p(losses, wins))
        self.assertEqual('inconclusive', review.verdict([comp(6, 3)]))                       # nine discordant blocks
        self.assertEqual('improved', review.verdict([comp(14, 6), comp(15, 5)]))
        self.assertEqual('not shown', review.verdict([comp(14, 6), comp(13, 7)]))            # one comparison short of alpha
        self.assertEqual('harmed', review.verdict([comp(5, 15), comp(4, 14)]))
        self.assertEqual('not shown', review.verdict([comp(10, 10)]))

    def test_cut_is_computed_from_the_spans(self):
        point = dict(start=100, end=200)
        self.assertFalse(review.cut(point, (50, 250)))
        self.assertTrue(review.cut(point, (150, 400)))
        self.assertTrue(review.cut(point, (0, 150)))

    def test_sample_takes_six_per_arm_by_hash_order_and_covers_both_arms(self):
        items = [dict(id=f'i{n}', kind='record') for n in range(30)]
        versions = dict(arms={i['id']: (['u'] if n % 3 == 0 else ['x1'] if n % 3 == 1 else ['b1']) for n, i in enumerate(items)})
        chosen = review.sample_ids(dict(items=items), versions)
        self.assertEqual(12, len(chosen))
        self.assertEqual(6, sum('u' in versions['arms'][c] for c in chosen))
        self.assertEqual(6, sum('x1' in versions['arms'][c] for c in chosen))
        self.assertTrue(all('b1' not in versions['arms'][c] for c in chosen))
        self.assertEqual(chosen, review.sample_ids(dict(items=list(reversed(items))), versions))    # by rule, not by order

    def test_the_bootstrap_is_deterministic_and_needs_two_sermons(self):
        diffs, video = {'a': 1.0, 'b': -0.5, 'c': 0.5, 'd': 0.0}, {'a': 1, 'b': 2, 'c': 3, 'd': 4}
        self.assertEqual(review.cluster_bootstrap(diffs, video), review.cluster_bootstrap(diffs, video))
        self.assertIsNone(review.cluster_bootstrap({'a': 1.0}, {'a': 1}))


if __name__ == '__main__':
    unittest.main()
