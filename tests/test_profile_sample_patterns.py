"""Conservative aggregation over an existing evidence ledger, without inference."""
from copy import deepcopy
import unittest

from pastor_transcript_extractor import profile_presentation as p
from test_profile_presentation import two_sermons


class PatternTests(unittest.TestCase):
    def test_recording_first_and_duplicate_references_do_not_add_membership(self):
        record = two_sermons()
        record['claims'].append(deepcopy(record['claims'][0]))
        for o in record['observations']:
            o['full_target_text'] = 'Identical complete source window.'
        reader = p.build_reader(record)
        summary = reader['sample_patterns']
        self.assertEqual([1, 2], [r['video_id'] for r in summary['recordings']])
        topic = next(g for g in summary['patterns'] if g['layer'] == 'topic')
        self.assertEqual([1, 2], topic['video_ids'])
        self.assertEqual(['topic-1'], topic['by_recording'][1])
        self.assertEqual(1, len(summary['duplicate_content_groups']))
        self.assertIn('independence', summary['scope'])
        self.assertNotIn('consistently', ' '.join(c['wording'] for c in reader['claims']))

    def test_missing_below_threshold_and_not_admitted_do_not_become_negative_positions(self):
        record = two_sermons()
        record['observations'][3]['state'] = 'measured_below_threshold'
        record['observations'].append(dict(id='saved-raw', video_id=2, block_id=4,
            layer='cached_leaf', field='directive', state='measured_not_admitted', value=.99))
        record['salvation_block_states'] = [dict(video_id=1, block_id=5, state='unrouted_unmeasured'),
            dict(video_id=2, block_id=5, state='missing_compatible_routed_result')]
        record['unresolved_leaves'] = ['repentance']
        reader = p.build_reader(record)
        by_recording = {r['video_id']: r for r in reader['sample_patterns']['recordings']}
        self.assertIn('measured_below_threshold', by_recording[1]['observation_states'])
        self.assertIn('measured_not_admitted', by_recording[2]['observation_states'])
        self.assertNotIn('saved-raw', by_recording[2]['supported_observation_ids'])
        self.assertEqual('unrouted_unmeasured', by_recording[1]['salvation_block_states'][0]['state'])
        self.assertEqual('missing_compatible_routed_result', by_recording[2]['salvation_block_states'][0]['state'])
        self.assertEqual(['repentance'], by_recording[2]['unresolved_leaves'])
        self.assertFalse(any(g['layer'] == 'cached_leaf' for g in reader['sample_patterns']['patterns']))
        self.assertFalse(any('rejects' in c['wording'] or 'denies' in c['wording'] for c in reader['claims']))

    def test_counterevidence_and_missing_recording_survive_shared_summary(self):
        record = two_sermons()
        record['source_identity'].append(dict(video_id=3, title='Third', source_sha256='three'))
        record['claims'][0]['counterevidence_ids'] = ['topic-1']
        record['claims'][0]['observation_input_ids'] = ['topic-1']
        reader = p.build_reader(record)
        topic = next(g for g in reader['sample_patterns']['patterns'] if g['layer'] == 'topic')
        self.assertEqual([3], topic['recordings_without_support'])
        self.assertEqual(['topic-1'], topic['counterevidence_ids'])
        recurring = next(c for c in reader['claims'] if c['id'] == 'reader-recurring-emphases')
        self.assertEqual(['topic-1'], recurring['counterevidence_ids'])
        self.assertIn('not absence', topic['withholding'])
        self.assertFalse(any(c['id'] == 'reader-shared-emphases' for c in reader['claims']))
        self.assertIn('no claim', topic['withholding'])

    def test_quotes_and_selected_examples_are_not_aggregation_inputs(self):
        record = two_sermons()
        original = p.build_reader(record)
        record['quotes'] = [dict(text='Invented quote', interpretation='Unsupported claim')]
        record['supporting_examples'] = [dict(claim_id='reader-shared-emphases', selected_blocks=[])]
        self.assertEqual(original, p.build_reader(record))
        self.assertTrue(all(c['rule_id'] and c['evidence_ids'] and c['recording_support'] for c in original['claims']))


if __name__ == '__main__':
    unittest.main()
