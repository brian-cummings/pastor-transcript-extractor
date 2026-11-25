import unittest

from pastor_transcript_extractor.church_fit import reading


def _blocks(share, name, n=20, extra=None):
    return {'blocks': [{'start_seconds': i * 60.0, 'text': f'b{i}',
                        'signals': {name: 0.9 if i < share * n else 0.1, **(extra or {})}} for i in range(n)]}


class ChurchFitTests(unittest.TestCase):
    def test_ranks_on_want_concerns_and_lists_avoid_matches_without_netting_them(self):
        concerns = {'version': 't', 'importance_weights': {'high': 2, 'medium': 1}, 'concerns': [
            {'id': 'W', 'kind': 'want', 'name': 'w', 'importance': 'high', 'for': ['L:serve'], 'against': []},
            {'id': 'A', 'kind': 'avoid', 'name': 'a', 'importance': 'high', 'for': ['L:civic_action'], 'against': []}]}
        sermons, scored, video = [], {}, 0
        for p in range(8):
            for _ in range(3):
                video += 1
                sermons.append({'video_id': video, 'pastor': f'p{p}'})
                scored[video] = _blocks(0.05 * p, 'L:serve', extra={'L:civic_action': 0.9 if p == 7 else 0.0})
        sermons.append({'video_id': 999, 'pastor': 'p99'})       # one sermon: left out
        scored[999] = _blocks(1.0, 'L:serve')
        from pastor_transcript_extractor.benchmark_explainer import values
        dims = values.jev_dimensions(scored.values())
        table = values.pastor_values(scored, {}, sermons, dims)
        result = reading(concerns, sermons, scored, {}, table)
        self.assertEqual(result['ranked'][0], 'p7')
        self.assertNotIn('p99', result['pastors'])
        self.assertTrue(result['pastors']['p7']['avoids']['A']['review'])
        self.assertFalse(result['pastors']['p6']['avoids']['A']['review'])


if __name__ == '__main__':
    unittest.main()
