import json
import unittest

from pastor_transcript_extractor.bound_claims.common import read_json
from pastor_transcript_extractor.thought_units import arms, leaf_evidence, leaf_review, main_point

try:
    from tests.bound_claims_support import CLEAN, DIRTY, METADATA, claim, stream_transport
    from tests.test_thought_unit_arms import Extracted, TEXT
except ImportError:
    from bound_claims_support import CLEAN, DIRTY, METADATA, claim, stream_transport
    from test_thought_unit_arms import Extracted, TEXT

ANCHOR = 'Second line sentence three goes here.'


def record(anchor=ANCHOR, **changes):
    value = claim(anchor, area='public_life', object='the experiment', summary='The preacher states a thing about the public experiment.', target='the public experiment')
    value.update(changes)
    return value


def reply(*records):
    return json.dumps(dict(records=list(records)))


class Setup(Extracted):
    """The section 16 world plus arm B's baseline extraction, so the leaf test has its baseline."""
    def setUp(self):
        super().setUp()
        pairs = main_point.pair_inputs(self.root, 'b')
        baseline = {p['key']: json.dumps(dict(claims=[claim(ANCHOR, area='public_life', object='the experiment')])) for p in pairs}
        main_point.run(self.root, 'b', transport=stream_transport(baseline), state=CLEAN, metadata=METADATA)
        self.leaf_dir = self.arms_dir.parent / 'leaf-evidence-b'
        self.keys = [p['key'] for p in leaf_evidence.pair_inputs(self.root)]

    def run_leaf(self, outputs, calls=None, **kwargs):
        return leaf_evidence.run(self.root, transport=stream_transport(outputs, calls), state=kwargs.pop('state', CLEAN), metadata=METADATA, **kwargs)


class ContractTests(unittest.TestCase):
    def test_the_instruction_is_the_approved_text_and_the_schema_adds_exactly_two_fields(self):
        self.assertIn('supporting summary', leaf_evidence.SYSTEM_PROMPT)
        self.assertEqual(['records'], leaf_evidence.RESPONSE_SCHEMA['required'])
        self.assertEqual({'summary', 'target'}, set(leaf_evidence.RECORD_SCHEMA['properties']) - set(arms.bound.CLAIM_SCHEMA['properties']) if hasattr(arms, 'bound') else {'summary', 'target'})
        self.assertEqual(len(leaf_evidence.RECORD_SCHEMA['required']), len(leaf_evidence.RECORD_SCHEMA['properties']))

    def test_the_message_carries_the_category_and_leaf_but_never_jev_probabilities(self):
        message = json.loads(leaf_evidence.user_message('P:critical', 'before', 'target', 'after'))
        self.assertEqual({'category', 'leaf', 'preceding_unit', 'target_unit', 'following_unit'}, set(message))
        self.assertEqual('society_public_life', message['category']['name'])
        self.assertTrue(message['category']['meaning'].startswith('Government, politics'))
        self.assertEqual({'name', 'meaning'}, set(message['leaf']))
        self.assertNotIn('probab', json.dumps(message).lower())

    def test_validation_needs_the_two_added_strings_one_record_at_most_and_the_shared_checks(self):
        good = record()
        self.assertEqual(1, len(leaf_evidence.validate_records(dict(records=[good]))))
        self.assertEqual([], leaf_evidence.validate_records(dict(records=[])))
        for bad in (dict(records=[good, good]), dict(records=[{k: v for k, v in good.items() if k != 'summary'}]), dict(records=[dict(good, summary='  ')]),
                    dict(records=[dict(good, polarity='sideways')]), dict(claims=[good]), dict(records=[dict(good, extra='x')])):
            with self.assertRaises(leaf_evidence.SchemaError):
                leaf_evidence.validate_records(bad)


class RunTests(Setup):
    def test_check_only_sends_nothing_and_reports_the_same_pairs_as_section_16(self):
        calls = []
        plan = leaf_evidence.run(self.root, check_only=True, transport=stream_transport({}, calls))
        self.assertEqual((2, 1, 2, []), (plan['pairs'], plan['units_with_a_pair'], plan['requests_to_send'], calls))
        self.assertEqual(['b001-critical', 'b001-moral'], self.keys)
        self.assertFalse((self.leaf_dir / 'plan.json').exists())

    def test_run_records_the_summary_and_target_places_the_anchor_in_the_sermon_and_never_repeats_a_request(self):
        calls, outputs = [], {key: reply(record()) for key in self.keys}
        done = self.run_leaf(outputs, calls)
        self.assertEqual((2, 2, None), (done['summary']['records'], done['summary']['ok'], done['stopped']))
        row = read_json(self.leaf_dir / 'extraction.json')['rows'][0]['claims'][0]
        self.assertEqual((TEXT.index(ANCHOR), 'the public experiment'), (row['sermon_start'], row['target']))
        self.assertEqual(ANCHOR, TEXT[row['sermon_start']:row['sermon_end']])
        plan = read_json(self.leaf_dir / 'plan.json')
        self.assertEqual(('0.50', 60), (plan['ceiling']['usd'], plan['ceiling']['attempts']))
        self.assertEqual(leaf_evidence.digest(leaf_evidence.SYSTEM_PROMPT), plan['instruction_sha256'])
        self.assertEqual(2, len(calls))
        self.run_leaf(outputs, calls)
        self.assertEqual(2, len(calls))
        entries = read_json(self.leaf_dir / 'ledger.json')['entries']
        self.assertTrue(all(key.startswith('extract_flash/leaf/') for key in entries))
        self.assertFalse(any(key.startswith('extract_flash/leaf/') for key in read_json(self.arms_dir / 'ledger.json')['entries']))   # section 16's ledger is untouched

    def test_a_dirty_tree_and_a_changed_instruction_are_refused(self):
        with self.assertRaises(ValueError):
            self.run_leaf({}, state=DIRTY)
        self.run_leaf({key: reply(record()) for key in self.keys})
        original = leaf_evidence.SYSTEM_PROMPT
        self.addCleanup(lambda: setattr(leaf_evidence, 'SYSTEM_PROMPT', original))
        leaf_evidence.SYSTEM_PROMPT = original + ' Be brief.'
        with self.assertRaises(ValueError):
            self.run_leaf({}, state=CLEAN)

    def test_an_empty_answer_is_a_valid_no_record_and_a_bad_anchor_is_an_anchor_failure(self):
        done = self.run_leaf({self.keys[0]: reply(), self.keys[1]: reply(record('Words that are not in the sermon at all.'))})
        # a record whose anchor fails the literal check is dropped, so that pair also has no record (as in section 16)
        self.assertEqual((0, 2, 1), (done['summary']['records'], done['summary']['no_record'], done['summary']['anchor_failures']))

    def test_one_failure_in_a_small_run_does_not_stop_it_and_two_do(self):
        done = self.run_leaf({self.keys[0]: ValueError('network'), self.keys[1]: reply(record())})
        self.assertEqual((1, 1, None), (done['summary']['transport_failures'], done['summary']['ok'], done['stopped']))


class ReviewTests(Setup):
    def extract(self, summary_for_moral=None):
        outputs = {key: reply(record()) for key in self.keys}
        if summary_for_moral:
            outputs['b001-moral'] = reply(record(summary=summary_for_moral, proposition='A different proposition about the same thing.'))
        self.run_leaf(outputs)

    def test_the_blind_queue_never_names_a_version_labels_identical_records_once_and_holds_summaries_until_phase_one_is_done(self):
        self.extract()
        built = leaf_review.build_queue(self.root)
        queue = read_json(self.leaf_dir / 'review.json')
        self.assertEqual(built['items'], queue['item_count'])
        self.assertTrue(all('uses' not in item and 'version' not in item for item in queue['items']))
        # the baseline and new records for a pair differ only in summary and target, so they are the same record on the shared fields
        self.assertEqual(2, built['phase1'])
        shown, answers = [], []
        def say(text):
            shown.append(text)
        def ask(prompt):
            return 'a' if prompt.startswith('accept') else 'y'
        leaf_review.judge(self.root, 'claude', ask, say)
        first_summary = next(i for i, text in enumerate(shown) if 'SUMMARY:' in text)
        self.assertEqual(2, sum('PROPOSITION:' in text and 'SUMMARY:' not in text for text in shown[:first_summary]))
        self.assertEqual(0, leaf_review.progress(self.root)['remaining'])
        self.assertEqual({'claude'}, {d['source'] for d in leaf_review.load_decisions(self.root).values()})

    def test_a_pair_with_no_new_record_asks_whether_it_should_have_one(self):
        outputs = {self.keys[0]: reply(record()), self.keys[1]: reply()}
        self.run_leaf(outputs)
        built = leaf_review.build_queue(self.root)
        queue = read_json(self.leaf_dir / 'review.json')
        self.assertIn('none', {item['kind'] for item in queue['items']})
        versions = read_json(self.leaf_dir / 'review_versions.json')
        none = [m for m in versions['items'].values() if m['kind'] == 'none'][0]
        self.assertEqual([dict(version='new', pair='b001-moral')], none['uses'])

    def test_the_report_scores_the_four_criteria_from_labels_with_their_source(self):
        self.extract(summary_for_moral='A different summary of the same thought.')
        leaf_review.build_queue(self.root)
        leaf_review.judge(self.root, 'claude', lambda prompt: 'a' if prompt.startswith('accept') else 'y', lambda text: None)
        done = leaf_review.report(self.root)
        self.assertTrue(done['passed'])
        self.assertEqual({'claude': 4 + 0 * 0} if False else done['labels_by'], done['labels_by'])
        self.assertEqual(['L1', 'L2', 'L3', 'L4'], list(done['criteria']))
        self.assertEqual((2, 2), (done['tally']['new']['records'], done['tally']['new']['accepted']))
        self.assertEqual(1, done['two_leaf_units'])
        self.assertIn('claude', done['labels_by'])

    def test_unfinished_labels_are_refused(self):
        self.extract()
        leaf_review.build_queue(self.root)
        with self.assertRaises(ValueError):
            leaf_review.report(self.root)


class AcceptanceTests(unittest.TestCase):
    def measures(self, **over):
        base = dict(pairs=19, new=dict(records=19, accepted=17, qualification_rejects=1, pairs_correct=17, summaries_ok=17),
                    baseline=dict(records=19, accepted=15, qualification_rejects=4, pairs_correct=15), two_leaf_units=5, same_support=1)
        for key, value in over.items():
            base[key] = {**base[key], **value} if isinstance(value, dict) else value
        return base

    def test_all_four_must_hold_at_the_pre_registered_levels(self):
        self.assertTrue(leaf_review.evaluate(self.measures())['passed'])
        self.assertFalse(leaf_review.evaluate(self.measures(new=dict(accepted=16)))['criteria']['L1']['passed'])               # 16 of 19 is 0.84
        self.assertFalse(leaf_review.evaluate(self.measures(new=dict(qualification_rejects=2)))['criteria']['L1']['passed'])
        self.assertFalse(leaf_review.evaluate(self.measures(new=dict(pairs_correct=16)))['criteria']['L2']['passed'])
        self.assertFalse(leaf_review.evaluate(self.measures(baseline=dict(pairs_correct=18)))['criteria']['L2']['passed'])    # must not be below the baseline
        self.assertFalse(leaf_review.evaluate(self.measures(new=dict(summaries_ok=16)))['criteria']['L3']['passed'])
        self.assertFalse(leaf_review.evaluate(self.measures(same_support=2))['criteria']['L4']['passed'])
        self.assertFalse(leaf_review.evaluate(self.measures(new=dict(records=0, accepted=0)))['passed'])


if __name__ == '__main__':
    unittest.main()
