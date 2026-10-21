"""Product-language boundaries independent of the profile 318 wording."""
from copy import deepcopy
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import unittest

from pastor_transcript_extractor import profile_presentation as p
from pastor_transcript_extractor import profile_description as d
from test_profile_description import fixture


class VisibleText(HTMLParser):
    """Text shown without opening technical disclosures, with optional reader opens."""
    def __init__(self, open_ids=()):
        super().__init__()
        self.open_ids = set(open_ids)
        self.stack = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        visible = True
        if self.stack:
            parent = self.stack[-1]
            visible = parent[1] and (not parent[2] or tag == 'summary')
        visible = visible and tag not in ('style', 'script', 'head')
        closed = tag == 'details' and 'open' not in attrs and attrs.get('id') not in self.open_ids
        if tag not in ('meta', 'br', 'hr', 'link', 'input'):
            self.stack.append((tag, visible, closed))

    def handle_endtag(self, tag):
        while self.stack:
            if self.stack.pop()[0] == tag:
                break

    def handle_data(self, data):
        if self.stack and self.stack[-1][1]:
            self.text.append(data)


def two_sermons():
    """Two sermons, with unequal numbers of segments carrying one theme."""
    sources = [dict(video_id=1, title='Faith and Life', source_sha256='one'), dict(video_id=2, title='The Public Square', source_sha256='two')]
    obs = []
    claims = []
    for vid, topic in ((1, 'god_character_action'), (2, 'god_character_action')):
        key = f'topic-{vid}'
        obs.append(dict(id=key, video_id=vid, block_id=1, layer='topic', field=topic))
        claims.append(dict(id=f'claim-{vid}', rule='topic', evidence_ids=[key]))
    for vid, block in ((1, 1), (1, 2), (2, 1)):
        key = f'salvation-{vid}-{block}'
        obs.append(dict(id=key, video_id=vid, block_id=block, layer='salvation', field='divine_grace_initiative', state='observed'))
        claims.append(dict(id='claim-'+key, rule='salvation', evidence_ids=[key]))
    return dict(profile={}, source_identity=sources, observations=obs, claims=claims)


def review_for(record, dimension='practical_application'):
    o = next(o for o in record['observations'] if o['field'] == dimension)
    return dict(evidence_id=o['id'], video_id=o['video_id'], block_id=o['block_id'], dimension=dimension,
        source_sha256=o['source_sha256'], start_seconds=o['start_seconds'], end_seconds=o['end_seconds'],
        target_sha256=hashlib.sha256(o['full_target_text'].encode()).hexdigest(),
        description='The speaker gives practical directions about prayer.', reviewer='Source inspection', scope='This passage only')


class PresentationTests(unittest.TestCase):
    def test_theme_counts_distinct_sermons_not_segments(self):
        record = two_sermons()
        reader = p.build_reader(record)
        self.assertEqual('All 2 sermons', reader['themes'][0]['seen_in'])
        self.assertEqual([1, 2], reader['themes'][0]['video_ids'])
        record['observations'] = [o for o in record['observations'] if o['id'] != 'salvation-2-1']
        record['claims'] = [c for c in record['claims'] if c['id'] != 'claim-salvation-2-1']
        reader = p.build_reader(record)
        self.assertEqual('Faith and Life', reader['themes'][0]['seen_in'])
        self.assertFalse(any(c['id'] == 'reader-salvation-summary' for c in reader['claims']))

    def test_topics_summarize_existing_sermon_membership_without_stability(self):
        reader = p.build_reader(two_sermons())
        shared = next(c for c in reader['claims'] if c['id'] == 'reader-shared-emphases')
        self.assertEqual({'topic-1', 'topic-2'}, set(shared['evidence_ids']))
        self.assertIn('shared focus', shared['wording'])
        self.assertIn('not agreement', shared['reason'])
        self.assertIn('Not a ministry-wide assessment', reader['at_a_glance'][-1]['description'])

    def test_style_requires_exact_source_inspection_not_a_probability(self):
        record = d.build(*fixture(text='Read the Bible and pray every day.'))
        self.assertIsNone(record['reader']['style_claim_id'])
        review = review_for(record)
        reader = p.build_reader(record, {'reviews': [review]})
        self.assertEqual('reader-style', reader['style_claim_id'])
        self.assertIn('Practical application is present', reader['at_a_glance'][3]['description'])
        for key in ('source_sha256', 'target_sha256', 'start_seconds', 'dimension'):
            changed = deepcopy(review); changed[key] = 'changed'
            reader = p.build_reader(record, {'reviews': [changed]})
            self.assertIsNone(reader['style_claim_id'], key)

    def test_source_title_name_is_metadata_and_requires_all_distinct_sources(self):
        record = two_sermons()
        record['source_identity'][0]['title'] += ', Pastor Ada Example'
        record['source_identity'][1]['title'] += ', Pastor Ada Example'
        metadata = [dict(video_id=s['video_id'], source_sha256=s['source_sha256'], speaker_name_in_title='Ada Example') for s in record['source_identity']]
        reader = p.build_reader(record, {'title_metadata': metadata})
        self.assertEqual('Pastor assessment', reader['title'])
        self.assertIn('Source titles identify', reader['identity_note'])
        self.assertIn('not yet been confirmed', reader['identity_note'])
        reader = p.build_reader(record, {'title_metadata': [metadata[0], metadata[0]]})
        self.assertNotIn('Ada Example', reader['identity_note'])
        record['profile']['display_label'] = 'Accepted name'
        self.assertEqual('Accepted name', p.build_reader(record)['title'])

    def test_initial_and_reader_evidence_views_hide_machine_terms_and_ids(self):
        record = d.build(*fixture(routed=True))
        page = d.render(record)
        human_ids = [c['id'] for c in record['reader']['claims']]
        for opens in ([], human_ids, ['passage-9-1'], human_ids+['passage-9-1']):
            visible = VisibleText(opens); visible.feed(page)
            text = ' '.join(visible.text)
            for term in ('cached local observations', 'routed segments', 'measured local only', 'candidate windows', 'positive threshold', 'eligible representative', 'semantic admission', 'unrouted_unmeasured', 'compatible routed result', 'frozen observation thresholds', 'stale materializations', 'leaf identities', 'G1/G2/G3/A1', 'developed_emphasis_probability', 'cached-observation-wording-v1', 'video_id', 'block_id', 'Pastor profile 17', 'Recording 9', 'e-9-1-'):
                self.assertNotIn(term, text, (opens, term))
            self.assertIn('Technical details', text)
        self.assertIn('developed_emphasis_probability', page)  # retained behind disclosures
        self.assertIn('unrouted_unmeasured', d.render(d.build(*fixture())))

    def test_all_reader_clauses_have_observations_and_resolving_links(self):
        record = d.build(*fixture(routed=True))
        ids = {o['id'] for o in record['observations']}
        for claim in record['reader']['claims']:
            self.assertTrue(claim['evidence_ids'])
            self.assertLessEqual(set(claim['evidence_ids']), ids)
        claim_ids = {c['id'] for c in record['reader']['claims']}
        self.assertTrue(all(key in claim_ids for paragraph in record['assessment'] for text, key in paragraph))
        self.assertIn('View supporting passage', d.render(record))
        self.assertIn('Back to description:', d.render(record))

    def test_below_threshold_is_not_absence_or_denial_in_reader_summary(self):
        record = d.build(*fixture(routed=True))
        for o in record['observations']:
            if o['layer'] == 'salvation': o['state'] = 'measured_below_threshold'
        reader = p.build_reader(record)
        self.assertEqual([], reader['themes'])
        self.assertIn('not established', reader['at_a_glance'][2]['description'])
        self.assertFalse(any('rejects' in c['wording'] or 'denies' in c['wording'] for c in reader['claims']))

    def test_assessment_glance_and_examples_have_distinct_jobs(self):
        record = d.build(*fixture(text='The preacher explains Scripture, reasons, tells a story and gives guidance.'))
        reviews = [review_for(record, dimension=k) for k in p.STYLES]
        reader = p.build_reader(record, {'reviews':reviews})
        record['reader'] = reader
        record['assessment'] = reader['assessment']
        full_prose = next(c['wording'] for c in reader['claims'] if c['id'] == reader['style_claim_id'])
        glance = reader['at_a_glance'][0]['description']
        self.assertNotEqual(full_prose, glance)
        self.assertIn(' + ', glance)
        page = d.render(record)
        closer = page.split('id="dimension-style"',1)[1].split('id="dimension-emphases"',1)[0]
        self.assertNotIn(full_prose, closer)
        self.assertIn('Examples establish the presence', closer)
        emphasis_detail = page.split('id="dimension-emphases"',1)[1].split('id="dimension-salvation"',1)[0]
        shared_wording = next((c['wording'] for c in reader['claims'] if c['id'] == 'reader-emphases'), '')
        if shared_wording:
            self.assertNotIn(shared_wording, emphasis_detail)
        self.assertIn('Supporting passages', emphasis_detail)
        self.assertEqual('salvation received through faith', p.THEMES['faith_as_receiving_response'])

    def test_reviewed_local_readings_are_inspectable_proposals_without_promoting_claims(self):
        from pastor_transcript_extractor.theological_binding import bind
        from test_theological_binding import fixture as binding_fixture
        record = d.build(*fixture(text='God creates <Review>.'))
        before = deepcopy(record['reader']['assessment'])
        before_claims = deepcopy(record['reader']['claims'])
        rebuilt_assessment = p.build_reader(record)['assessment']
        texts, authored, provenance = binding_fixture('God creates <Review>.')
        authored['title'] = '<Local reading>'
        authored['unknowns'] = ['No <ministry conclusion>.']
        binding = bind(texts, authored, provenance)
        evidence_id = record['observations'][0]['id']
        record.setdefault('evidence_supply', {})['reviewed_bound_records'] = [dict(
            binding=binding, evidence_id=evidence_id,
            status='source_reviewed_proposal_not_production_admission')]
        page = d.render(record)
        md = p.markdown(record)
        for output in (page, md):
            self.assertIn('Reviewed local readings · proposals', output)
            self.assertIn('not production-admitted measurements or pastor-wide positions', output)
            self.assertIn('God creates &lt;Review&gt;.', output)
            self.assertIn('preacher · preacher · actual', output)
            self.assertIn('own assertion · Direct source-reviewed statement.', output)
            self.assertIn('Local statement only.', output)
            self.assertIn('No &lt;ministry conclusion&gt;.', output)
            self.assertIn('None bound to this proposition', output)
            self.assertIn('#passage-9-1', output)
            self.assertNotIn('<Local reading>', output)
            self.assertNotIn('<Review>', output)
        section = page.split('id="reviewed-local-readings"', 1)[1].split('</section>', 1)[0]
        self.assertIn('<details><summary>Inspect the existing source-reviewed local readings', section)
        self.assertNotIn('<details open', section)
        self.assertEqual(before, record['reader']['assessment'])
        self.assertEqual(before_claims, record['reader']['claims'])
        self.assertEqual(rebuilt_assessment, p.build_reader(record)['assessment'])

    def test_authored_review_input_is_bounded_and_not_an_identity_rule(self):
        reviews = p.load_reviews()
        self.assertEqual(4, len(reviews['reviews']))
        self.assertEqual(set(p.STYLES), {r['dimension'] for r in reviews['reviews']})
        self.assertTrue(all('pending' in r['reviewer'] for r in reviews['reviews']))
        self.assertIn('no raw results or new measurements', reviews['purpose'])
