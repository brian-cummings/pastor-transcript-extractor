"""Examples consume established support; they never create analytical authority."""
from copy import deepcopy
import hashlib
import unittest

from pastor_transcript_extractor import profile_description as description
from pastor_transcript_extractor import profile_presentation as presentation
from pastor_transcript_extractor import profile_supporting_blocks as examples
from test_profile_description import fixture


def record():
    return description.build(*fixture(routed=True))


class SupportingBlocksTests(unittest.TestCase):
    def test_pure_complete_blocks_preserve_point_source_and_counterevidence(self):
        profile = record()
        before = deepcopy(profile)
        result = examples.build(profile)
        self.assertEqual(before, profile)
        self.assertEqual(result, examples.build(profile))
        topic = next(c for c in profile['claims'] if c['rule'] == 'topic')
        item = next(item for item in result if item['claim_id'] == topic['id'])
        self.assertEqual(topic['wording'], item['point'])
        self.assertEqual(topic['counterevidence_ids'], item['counterevidence_ids'])
        self.assertEqual('selected', item['status'])
        block = item['selected_blocks'][0]
        source = next(o for o in profile['observations'] if o['id'] == block['evidence_id'])
        self.assertEqual(source['full_target_text'], block['full_target_text'])
        self.assertEqual(hashlib.sha256(source['full_target_text'].encode()).hexdigest(), block['target_sha256'])
        self.assertEqual(source['source_sha256'], block['source_sha256'])
        self.assertEqual('passage-9-1', block['passage_id'])
        self.assertIn('does not establish agreement', block['support_reason'])
        self.assertIn('does not establish frequency', item['qualifications'][-1])

    def test_unreviewed_treatment_and_unadmitted_cached_leaves_cannot_supply_examples(self):
        profile = record()
        treatment = next(o for o in profile['observations'] if o['layer'] == 'treatment')
        cached = dict(deepcopy(treatment), id='cached', layer='cached_leaf', state='measured_not_admitted')
        profile['observations'].append(cached)
        for key in (treatment['id'], 'cached'):
            profile['reader']['claims'].append(dict(id='unestablished-'+key, wording='Unsupported posture', evidence_ids=[key], rule_version='test'))
        result = examples.build(profile)
        self.assertTrue(all(item['status'] == 'unknown' for item in result if item['claim_id'].startswith('unestablished-')))
        self.assertFalse(any(item['claim_id'] == c.get('id') for c in profile['treatment_candidates'] for item in result))

    def test_reviewed_treatment_requires_exact_current_source_receipt(self):
        profile = record()
        o = next(o for o in profile['observations'] if o['field'] == 'practical_application')
        review = dict(evidence_id=o['id'], video_id=o['video_id'], block_id=o['block_id'], dimension=o['field'],
            source_sha256=o['source_sha256'], start_seconds=o['start_seconds'], end_seconds=o['end_seconds'],
            target_sha256=hashlib.sha256(o['full_target_text'].encode()).hexdigest(), description='A reviewed practical example.')
        profile['reader'] = presentation.build_reader(profile, dict(reviews=[review]))
        result = examples.build(profile)
        item = next(item for item in result if item['claim_id'] == 'reader-style')
        self.assertEqual('selected', item['status'])
        self.assertEqual(review, item['selected_blocks'][0]['source_review'])
        profile['reader']['source_reviews'][0]['target_sha256'] = 'stale'
        item = next(item for item in examples.build(profile) if item['claim_id'] == 'reader-style')
        self.assertEqual('unknown', item['status'])

    def test_topic_inputs_do_not_replace_missing_representative_support(self):
        profile = record()
        claim = profile['claims'][0]
        claim['evidence_ids'] = ['missing']
        item = next(item for item in examples.build(profile) if item['claim_id'] == claim['id'])
        self.assertEqual('unknown', item['status'])
        self.assertEqual([], item['selected_blocks'])
        self.assertTrue(claim['observation_input_ids'])

    def test_ineligible_or_changed_source_withholds_instead_of_text_search(self):
        for change in ('eligibility', 'source'):
            profile = record()
            if change == 'eligibility':
                profile['source_identity'][0]['gate']['eligible'] = False
            else:
                profile['source_identity'][0]['source_sha256'] = 'new-version'
            self.assertTrue(all(item['status'] == 'unknown' for item in examples.build(profile)))

    def test_ties_are_deterministic_and_each_recording_component_is_retained(self):
        profile = record()
        claim = next(c for c in profile['claims'] if c['rule'] == 'salvation')
        original = next(o for o in profile['observations'] if o['id'] == claim['evidence_ids'][0])
        # Three candidate blocks: a lower probability, then two equal-strength
        # windows with equal start times. Existing strength, time, block ID wins.
        for block_id, start, value in ((4, 120, .999), (3, 120, .999), (2, 60, .99)):
            new = dict(deepcopy(original), id=f'new-{block_id}', block_id=block_id,
                start_seconds=start, end_seconds=start+60, value=value)
            profile['observations'].append(new)
            claim['evidence_ids'].append(new['id'])
        # A different field in the same point needs its own example.
        other = dict(deepcopy(original), id='another-field', field='other-local-relationship')
        profile['observations'].append(other)
        claim['evidence_ids'].append(other['id'])
        # A second recording cannot be represented by the first recording's block.
        source = dict(deepcopy(profile['source_identity'][0]), video_id=10)
        profile['source_identity'].append(source)
        second = dict(deepcopy(original), id='second-recording', video_id=10)
        profile['observations'].append(second)
        claim['evidence_ids'].append(second['id'])
        selected = next(item for item in examples.build(profile) if item['claim_id'] == claim['id'])
        self.assertEqual([9, 10], selected['recording_ids'])
        self.assertEqual(3, len(selected['selected_blocks']))
        self.assertIn('new-3', [b['evidence_id'] for b in selected['selected_blocks']])
        profile['observations'].reverse()
        self.assertEqual(selected, next(item for item in examples.build(profile) if item['claim_id'] == claim['id']))

    def test_partial_support_and_conflicting_source_copies_are_visible(self):
        profile = record()
        profile['claims'][0]['evidence_ids'].append('missing')
        selected = examples.build(profile)[0]
        self.assertEqual('partial', selected['status'])
        self.assertEqual('missing', selected['withheld_observations'][0]['evidence_id'])
        duplicate = dict(deepcopy(profile['observations'][0]), id='conflicting', full_target_text='Different text')
        profile['observations'].append(duplicate)
        with self.assertRaisesRegex(ValueError, 'Conflicting source block'):
            examples.build(profile)


if __name__ == '__main__':
    unittest.main()
