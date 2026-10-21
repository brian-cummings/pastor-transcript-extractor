"""Explanations preserve authored meanings and fail closed on incompatible evidence."""
from copy import deepcopy
import unittest

from pastor_transcript_extractor import profile_explanatory_descriptions as d
from pastor_transcript_extractor.binding_evidence import text_digest
from pastor_transcript_extractor.theological_binding import bind
from test_theological_binding import fixture


def inputs(text='God creates the world.'):
    texts, authored, provenance = fixture(text)
    provenance.update(video_id=42, block_id=7, source_inventory_fingerprint='inventory',
                      membership_fingerprint='membership')
    observation = dict(id='observation', video_id=42, block_id=7, source_sha256='source',
                       full_target_text=text, field='practical_application', layer='treatment',
                       start_seconds=60, end_seconds=120)
    record = dict(inventory_fingerprint='inventory', profile=dict(membership_fingerprint='membership'),
                  source_identity=[dict(video_id=42, source_sha256='source')], observations=[observation],
                  evidence_supply=dict(reviewed_bound_records=[dict(binding=bind(texts, authored, provenance),
                      evidence_id='observation', status=d.PROPOSAL, original_g1_record_unchanged=True)]))
    review = dict(evidence_id='observation', video_id=42, block_id=7, dimension='practical_application',
                  source_sha256='source', target_sha256=text_digest(text), start_seconds=60, end_seconds=120,
                  description='The speaker gives practical directions about prayer.', scope='This example only.')
    return record, dict(source_reviews=[review])


class ExplanatoryDescriptionTests(unittest.TestCase):
    def test_authored_content_and_every_clause_remain_source_linked_without_mutation(self):
        record, reader = inputs()
        before = deepcopy((record, reader))
        result = d.build(record, reader)
        self.assertEqual(before, (record, reader))
        self.assertEqual([], result['withheld'])
        self.assertEqual(2, len(result['points']))
        self.assertEqual([p['point_id'] for p in result['points']], result['by_recording']['42'])
        style, reading = result['points']
        self.assertEqual(reader['source_reviews'][0]['description'], style['explanation'])
        self.assertEqual('God creates the world.', reading['explanation'])
        self.assertEqual(d.PROPOSAL, reading['status'])
        self.assertEqual('compatible', reading['source_compatibility']['status'])
        for point in result['points']:
            self.assertEqual(['passage-42-7'], point['passage_ids'])
            self.assertTrue(point['clauses'])
            for clause in point['clauses']:
                self.assertEqual(['observation'], clause['evidence_ids'])
                self.assertEqual(point['reviewed_binding_ids'], clause['reviewed_binding_ids'])

    def test_no_records_never_fall_back_to_topic_or_raw_text_inference(self):
        record, reader = inputs()
        record['evidence_supply']['reviewed_bound_records'] = []
        self.assertEqual([], d.build(record, {})['points'])
        record['observations'][0].update(probability=1.0, field='divine_grace_initiative')
        self.assertEqual([], d.build(record, {})['points'])
        self.assertEqual({}, d.build(record, {})['by_recording'])

    def test_changed_review_is_withheld_without_remapping_to_nearby_source(self):
        for field in ('source_sha256', 'target_sha256', 'video_id', 'block_id', 'dimension', 'start_seconds', 'end_seconds'):
            record, reader = inputs()
            reader['source_reviews'][0][field] = 'different'
            result = d.build(record, reader)
            self.assertEqual(['reviewed_binding'], [p['kind'] for p in result['points']], field)
            self.assertEqual(1, len(result['withheld']), field)

    def test_stale_binding_scope_or_changed_literal_target_fails_closed(self):
        for field in ('source_sha256', 'target_sha256', 'video_id', 'block_id',
                      'source_inventory_fingerprint', 'membership_fingerprint'):
            record, reader = inputs()
            record['evidence_supply']['reviewed_bound_records'][0]['binding']['provenance'][field] = 'different'
            result = d.build(record, {})
            self.assertEqual([], result['points'], field)
            self.assertEqual(1, len(result['withheld']), field)
        record, reader = inputs()
        binding = record['evidence_supply']['reviewed_bound_records'][0]['binding']
        binding['proposition']['span']['text'] = 'Invented words.'
        self.assertEqual([], d.build(record, {})['points'])

    def test_projected_report_rejection_and_uncertainty_keep_distinct_frames(self):
        record, reader = inputs('Can you say God creates?')
        item = record['evidence_supply']['reviewed_bound_records'][0]
        binding = item['binding']
        binding['voice'].update(kind='quoted_or_reported', speaker='invited listener', occurrence='projected')
        binding['adoption'].update(status='undetermined', basis='unresolved')
        binding['epistemic_status']['value'] = 'expressed_uncertainty'
        binding['conditions'] = [dict(kind='condition', span=deepcopy(binding['proposition']['span']),
                                      rationale='Authored condition, not a new sufficient condition.')]
        result = d.build(record, {})['points'][0]
        self.assertIn('not establish that the words were actually spoken', result['voice_note'])
        self.assertIn('undetermined', result['use_note'])
        self.assertEqual(binding['conditions'], result['frame']['conditions'])
        self.assertEqual(binding['epistemic_status'], result['frame']['epistemic_status'])
        binding['voice']['occurrence'] = 'actual'
        binding['adoption']['status'] = 'rejected'
        result = d.build(record, {})['points'][0]
        self.assertIn('reported speech', result['voice_note'])
        self.assertIn('rejecting this proposition; no opposite proposition', result['use_note'])
        self.assertEqual(binding['proposition']['reading'], result['explanation'])

    def test_explicit_counterevidence_preserved_and_missing_reference_withheld(self):
        record, reader = inputs()
        item = record['evidence_supply']['reviewed_bound_records'][0]
        contrary = deepcopy(record['observations'][0]); contrary['id'] = 'contrary'
        record['observations'].append(contrary)
        item['counterevidence_ids'] = ['contrary']
        point = d.build(record, {})['points'][0]
        self.assertEqual(['contrary'], point['counterevidence_ids'])
        item['counterevidence_ids'] = ['absent']
        self.assertEqual([], d.build(record, {})['points'])

    def test_duplicate_inputs_do_not_multiply_points_and_order_does_not_change_identity(self):
        record, reader = inputs()
        before = d.build(record, reader)
        reader['source_reviews'] *= 2
        record['evidence_supply']['reviewed_bound_records'] *= 2
        after = d.build(record, reader)
        self.assertEqual(before, after)

    def test_no_new_quote_dependency_or_g1_interpretation(self):
        record, reader = inputs()
        item = record['evidence_supply']['reviewed_bound_records'][0]
        item['assurance_interpretation'] = dict(g1_record={'unchanged': True})
        before = deepcopy(item)
        points = d.build(record, reader)['points']
        record['quotes'] = [{'status': 'rejected', 'text': 'irrelevant'}]
        self.assertEqual(points, d.build(record, reader)['points'])
        self.assertEqual(before, item)
        for field, value in (('original_g1_record_unchanged', False), ('status', 'production_admitted')):
            changed = deepcopy(record)
            changed['evidence_supply']['reviewed_bound_records'][0][field] = value
            self.assertEqual([], d.build(changed, {})['points'])


if __name__ == '__main__':
    unittest.main()
