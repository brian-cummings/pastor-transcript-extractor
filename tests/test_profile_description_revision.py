"""Independent source and reader-utility boundaries for description revision D1–D4."""
from copy import deepcopy
import re
import unittest

from pastor_transcript_extractor import profile_description as description
from pastor_transcript_extractor import profile_presentation as presentation
from pastor_transcript_extractor import theological_binding
from pastor_transcript_extractor.assurance_binding_adapter import interpret
from test_profile_binding_pilot import TEXT, row as original_reading
from test_profile_description import fixture
from test_profile_presentation import VisibleText, review_for
from test_theological_binding import fixture as generic_fixture


def supplied_record(mode='own'):
    """A compiled frozen G1 control with exact current synthetic profile identity."""
    record = description.build(*fixture(text=TEXT))
    observation = record['observations'][0]
    texts, authored, provenance = generic_fixture(TEXT)
    authored['title'] = 'A reviewed present-acceptance reading'
    if mode == 'reported':
        authored['voice'].update(kind='quoted_or_reported', speaker='a reported speaker')
        authored['adoption'].update(status='reported_not_adopted', basis='quotation_only')
    elif mode == 'projected':
        authored['voice'].update(kind='quoted_or_reported', speaker='invited listener', occurrence='projected')
        authored['adoption'].update(status='undetermined', basis='unresolved')
        authored['unknowns'].append('An invited response does not establish an actual listener response.')
    elif mode == 'ambiguous':
        authored['voice'].update(kind='unresolved', speaker=None, occurrence='unresolved')
        authored['adoption'].update(status='undetermined', basis='unresolved')
    provenance.update(video_id=observation['video_id'], block_id=observation['block_id'],
        source_sha256=observation['source_sha256'], source_inventory_fingerprint=record['inventory_fingerprint'],
        membership_fingerprint=record['profile']['membership_fingerprint'])
    binding = theological_binding.bind(texts, authored, provenance)
    assurance = interpret(binding, texts, original_reading())
    record['evidence_supply']['reviewed_bound_records'] = [dict(
        binding=binding, assurance_interpretation=assurance, evidence_id=observation['id'],
        status='source_reviewed_proposal_not_production_admission', original_g1_record_unchanged=True)]
    return record


class DescriptionRevisionTests(unittest.TestCase):
    def assemble(self, record, reviews=None):
        return presentation.build_reader(record, reviews)['explanatory_descriptions']

    def test_compatible_reading_keeps_provenance_and_does_not_mutate_original_evidence(self):
        record = supplied_record()
        before = deepcopy(record)
        result = self.assemble(record)
        self.assertEqual(before, record)
        point = next(p for p in result['points'] if p['kind'] == 'reviewed_binding')
        entry = record['evidence_supply']['reviewed_bound_records'][0]
        self.assertEqual(TEXT, point['explanation'])
        self.assertEqual([entry['binding']['binding_id']], point['reviewed_binding_ids'])
        self.assertEqual([entry['evidence_id']], point['evidence_ids'])
        self.assertEqual([9], point['video_ids'])
        self.assertEqual(['passage-9-1'], point['passage_ids'])
        self.assertEqual('compatible', point['source_compatibility']['status'])
        self.assertIn('proposal', point['status'])
        self.assertEqual([point['point_id']], result['by_recording']['9'])
        self.assertEqual(before['observations'], record['observations'])
        self.assertEqual(before['evidence_supply']['reviewed_bound_records'][0]['assurance_interpretation'], entry['assurance_interpretation'])
        self.assertTrue(point['clauses'])
        self.assertTrue(all(clause['evidence_ids'] for clause in point['clauses']))

    def test_stale_identity_or_unadmitted_status_cannot_supply_a_richer_description(self):
        for field in ('source_sha256', 'target_sha256', 'video_id', 'block_id',
                      'source_inventory_fingerprint', 'membership_fingerprint', 'status', 'original_g1_record_unchanged'):
            with self.subTest(field=field):
                record = supplied_record()
                entry = record['evidence_supply']['reviewed_bound_records'][0]
                if field == 'status':
                    entry[field] = 'unreviewed_candidate'
                elif field == 'original_g1_record_unchanged':
                    entry[field] = False
                else:
                    entry['binding']['provenance'][field] = 'stale'
                result = self.assemble(record)
                self.assertFalse(any(p['kind'] == 'reviewed_binding' for p in result['points']))
                self.assertTrue(result['withheld'])

    def test_reported_projected_and_ambiguous_voice_are_not_promoted_to_preacher_assertions(self):
        for mode in ('reported', 'projected', 'ambiguous'):
            with self.subTest(mode=mode):
                record = supplied_record(mode)
                original = deepcopy(record['evidence_supply']['reviewed_bound_records'][0]['binding'])
                point = next(p for p in self.assemble(record)['points'] if p['kind'] == 'reviewed_binding')
                self.assertEqual(original['voice'], point['frame']['voice'])
                self.assertEqual(original['adoption'], point['frame']['adoption'])
                self.assertEqual(original['scope'], point['frame']['scope'])
                self.assertEqual(original['conditions'], point['frame']['conditions'])
                self.assertEqual(original['unknowns'], point['frame']['unknowns'])
                self.assertNotEqual('own_assertion', point['frame']['adoption']['status'])
                self.assertIn('proposal', point['status'])

    def test_generic_fallback_and_single_style_review_need_no_fixed_number_of_inputs(self):
        record = description.build(*fixture(text='The speaker explains what acceptance means.'))
        self.assertEqual([], self.assemble(record)['points'])
        review = review_for(record, 'exegetical_exposition')
        review['description'] = 'Explains what acceptance means in this passage.'
        result = self.assemble(record, {'reviews': [review]})
        self.assertEqual(['style'], [p['kind'] for p in result['points']])
        self.assertEqual(review['description'], result['points'][0]['explanation'])
        stale = deepcopy(review); stale['source_sha256'] = 'stale'
        self.assertEqual([], self.assemble(record, {'reviews': [stale]})['points'])
        # A probability/treatment candidate alone supplies no authored explanation.
        self.assertTrue(record['treatment_candidates'])
        self.assertEqual([], self.assemble(record)['points'])

    def test_quote_or_selected_example_removal_does_not_change_description_authority(self):
        record = supplied_record('projected')
        before = self.assemble(record)
        record['supporting_examples'] = []
        record['quotes'] = [{'status': 'rejected', 'text': 'Invented theological claim.'}]
        after = self.assemble(record)
        self.assertEqual(before, after)

    def test_explanatory_content_is_visible_before_technical_disclosures_with_resolving_links(self):
        record = supplied_record('projected')
        record['reader'] = presentation.build_reader(record)
        record['assessment'] = record['reader']['assessment']
        page = description.render(record)
        visible = VisibleText(); visible.feed(page)
        text = ' '.join(visible.text)
        self.assertIn(TEXT, text)
        self.assertIn('invited listener', text)
        self.assertIn('projected', text)
        self.assertIn('proposal', text.lower())
        self.assertIn('An invited response does not establish an actual listener response.', text)
        self.assertLess(page.index(TEXT), page.index('id="technical-provenance"'))
        targets = set(re.findall(r' id="([^"]+)"', page))
        self.assertLessEqual(set(re.findall(r'href="#([^"]+)"', page)), targets)
        self.assertIn('index.html#passage-9-1', presentation.markdown(record))


if __name__ == '__main__':
    unittest.main()
