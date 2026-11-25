import unittest

from pastor_transcript_extractor.benchmark_explainer import values
from pastor_transcript_extractor.church_fit import reading
from pastor_transcript_extractor.pastor_report import assemble


def _sermon(share, n=20):
    return {'blocks': [{'start_seconds': i * 60.0, 'text': f'b{i}',
                        'signals': {'L:serve': 0.9 if i < share * n else 0.1, 'L:witness': 0.1}} for i in range(n)]}


class PastorReportTests(unittest.TestCase):
    def setUp(self):
        self.sermons, self.scored, video = [], {}, 0
        for p in range(8):
            for _ in range(4):
                video += 1
                self.sermons.append({'video_id': video, 'youtube_video_id': f'y{video}', 'pastor': f'p{p}'})
                self.scored[video] = _sermon(0.6 if p == 7 else 0.02 * p)
        self.dims = values.jev_dimensions(self.scored.values())
        self.table = values.pastor_values(self.scored, {}, self.sermons, self.dims)

    def test_offers_his_distinctive_stable_trait_with_breadth_and_passages(self):
        report = assemble('p7', self.sermons, self.scored, {}, self.table, self.dims)
        self.assertEqual([r['dimension'] for r in report['explained']], ['L:serve'])
        row = report['explained'][0]
        self.assertTrue(row['z'] > 0 and row['evidence'])
        self.assertEqual(row['breadth']['on_his_side'], 4)
        self.assertTrue(report['few_sermons'])
        self.assertIsNone(report['church_fit'])

    def test_church_fit_row_is_reused_unchanged(self):
        concerns = {'version': 't', 'importance_weights': {'high': 2, 'medium': 1}, 'concerns': [
            {'id': 'W', 'kind': 'want', 'name': 'w', 'importance': 'high', 'for': ['L:serve'], 'against': []}]}
        fit = reading(concerns, self.sermons, self.scored, {}, self.table)
        report = assemble('p7', self.sermons, self.scored, {}, self.table, self.dims, fit)
        self.assertIs(report['church_fit']['row'], fit['pastors']['p7'])
        self.assertEqual(report['church_fit']['row']['rank'], 1)

    def test_unknown_pastor_is_an_error(self):
        with self.assertRaises(ValueError):
            assemble('p999', self.sermons, self.scored, {}, self.table, self.dims)


if __name__ == '__main__':
    unittest.main()
