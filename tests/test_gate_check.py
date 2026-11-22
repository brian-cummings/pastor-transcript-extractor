import unittest

from pastor_transcript_extractor.thought_units import gate_check


class MeasureTests(unittest.TestCase):
    def table(self, rows):
        info = {f'p{n}': dict(set=s, leaf=leaf, probability=prob) for n, (s, leaf, prob, _level) in enumerate(rows)}
        decided = {f'p{n}': dict(level=level) for n, (_s, _l, _p, level) in enumerate(rows)}
        return info, decided

    def test_strict_and_lenient_precision_and_the_probability_bands(self):
        rows = [('v1', 'P:moral', 0.85, 'shows')] * 6 + [('v1', 'P:moral', 0.85, 'does_not_show')] * 4 + [('v2', 'P:theological', 0.93, 'shows')] * 4 + [('v2', 'P:theological', 0.93, 'borderline')]
        result = gate_check.measures(*self.table(rows))
        self.assertEqual((15, 10, 1, 4), (result['overall']['pairs'], result['overall']['shows'], result['overall']['borderline'], result['overall']['does_not_show']))
        self.assertAlmostEqual(0.667, result['overall']['strict'], places=3)
        self.assertEqual(0.6, result['by_band']['< 0.9']['strict'])
        self.assertEqual(0.8, result['by_band']['>= 0.9']['strict'])
        self.assertTrue(result['probability_informative'])          # 20 points apart, above 15
        self.assertFalse(result['gate_meets_bar'])                  # 0.667 is under 0.80

    def test_a_band_without_pairs_makes_the_probability_reading_undecidable(self):
        result = gate_check.measures(*self.table([('v1', 'P:moral', 0.85, 'shows')] * 3))
        self.assertIsNone(result['probability_informative'])

    def test_the_wilson_interval_contains_the_proportion(self):
        low, high = gate_check.wilson(8, 10)
        self.assertLess(low, 0.8)
        self.assertGreater(high, 0.8)
        self.assertIsNone(gate_check.wilson(0, 0))


if __name__ == '__main__':
    unittest.main()
