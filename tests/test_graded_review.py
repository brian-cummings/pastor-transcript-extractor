import unittest

from pastor_transcript_extractor.thought_units import graded_review


def summary(item, level, flag=False, framed=True):
    return dict(item=item, level=level, flag=flag, framed=framed, source='claude')


class MeasureTests(unittest.TestCase):
    def build(self, levels, pairs=()):
        items = [dict(id=f's{n}', kind='summary', leaf='P:moral') for n in range(len(levels))] + [dict(id=f'd{n}', kind='distinct_points', leaf='P:moral') for n in range(len(pairs))]
        decided = {f's{n}': summary(f's{n}', *level) for n, level in enumerate(levels)}
        decided.update({f'd{n}': dict(level=p) for n, p in enumerate(pairs)})
        return dict(items=items), decided

    def test_accuracy_counts_complete_and_accurate_incomplete_and_only_wrong_fails_it(self):
        queue, decided = self.build([('complete',)] * 7 + [('accurate_incomplete', True)] * 2 + [('wrong',)])
        result = graded_review.measures(queue, decided)
        self.assertEqual((7, 2, 1, 1), (result['complete'], result['accurate_incomplete'], result['wrong'], result['flagged'] - 1))
        self.assertAlmostEqual(0.9, result['accuracy'])
        self.assertTrue(result['accuracy_bar_met'])
        self.assertTrue(result['flag_defect'])         # 2 of 10 flagged is above 15%
        queue, decided = self.build([('complete',)] * 8 + [('wrong',)] * 2)
        self.assertFalse(graded_review.measures(queue, decided)['accuracy_bar_met'])

    def test_the_padding_reading_needs_twelve_multi_record_pairs(self):
        queue, decided = self.build([], ['distinct'] * 4 + ['same_point_twice'])
        result = graded_review.measures(queue, decided)
        self.assertIsNone(result['padding_reading'])
        self.assertIn('fewer than 12', result['padding_reading_note'])
        queue, decided = self.build([], ['distinct'] * 9 + ['overlapping'] * 2 + ['same_point_twice'])
        self.assertTrue(graded_review.measures(queue, decided)['padding_reading'])           # 1 of 12 is under 15%
        queue, decided = self.build([], ['distinct'] * 9 + ['same_point_twice'] * 3)
        self.assertFalse(graded_review.measures(queue, decided)['padding_reading'])          # 3 of 12 is over 15%

    def test_the_pilot_takes_summaries_by_hash_of_the_item_id(self):
        queue = dict(items=[dict(id=f's{n}', kind='summary') for n in range(30)] + [dict(id='d0', kind='distinct_points')])
        chosen = graded_review.pilot_ids(queue, 12)
        self.assertEqual(12, len(chosen))
        self.assertEqual(set(chosen), set(graded_review.pilot_ids(dict(items=list(reversed(queue['items']))), 12)))
        self.assertNotIn('d0', chosen)


if __name__ == '__main__':
    unittest.main()
