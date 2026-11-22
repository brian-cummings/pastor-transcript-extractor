from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.bound_claims.common import read_json, write_json
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.sermon_classifier_typesafe import TypeSafeBlockCache, topic_question_inventory
from pastor_transcript_extractor.sermon_topics import TopicBlockContext
from pastor_transcript_extractor.thought_units import arms, arms_review, main_point, snap, stage

try:
    from tests.bound_claims_support import CLEAN, DIRTY, METADATA, claim, stream_transport
except ImportError:
    from bound_claims_support import CLEAN, DIRTY, METADATA, claim, stream_transport

BLOCK0 = 'First line sentence one. First line sentence two here.\nSecond line sentence three goes here.'
BLOCK1 = 'Third block says the experiment is working brilliantly today. It also says more public things.'
TEXT = BLOCK0 + '\n\n' + BLOCK1
SIGNALS = {'T:society_public_life': 0.95, 'P:critical': 0.9, 'P:moral': 0.85, 'P:supportive': 0.5, 'P:theological': 0.82}


def after(phrase: str) -> int:
    return TEXT.index(phrase) + len(phrase)


def build_world(root: Path):
    """Two saved blocks (ids 10 and 11), three caption lines, four segments; sermon 281 as the frozen target."""
    blocks = [dict(coordinate='v281b10', block_id=10, text=BLOCK0, start_seconds=0.0, end_seconds=30.0, segment_indexes=[0, 1, 2],
                   ordinal=0, signals=dict(SIGNALS)),
              dict(coordinate='v281b11', block_id=11, text=BLOCK1, start_seconds=30.0, end_seconds=40.0, segment_indexes=[3],
                   ordinal=1, signals={**SIGNALS, 'T:society_public_life': 0.4})]
    write_json(root / 'leaf.json', dict(sermons=[dict(video_id=281, title='Sermon', url='https://youtu.be/x', source_sha256='s' * 64, blocks=blocks)]))
    units = lambda *sources: [dict(source_segment_indexes=list(s)) for s in sources]
    segments = [dict(start_seconds=10.0 * i, end_seconds=10.0 * i + 9.0, text=f'caption {i}', label='sermon', speaker_hint=None, confidence=None)
                for i in range(4)]
    write_json(root / 'proposed.json', dict(
        segments=segments,
        classification=dict(blocks=[dict(block_id=10, text=BLOCK0, normalization=dict(normalized_units=units([0], [1, 2]))),
                                    dict(block_id=11, text=BLOCK1, normalization=dict(normalized_units=units([3])))])))
    write_json(root / 'slice.json', dict(sermons=[dict(video_id=281, source_path=str(root / 'proposed.json'), cache_dir=str(root / 'pilot-cache'),
                                                       model='jev-1.13.0')]))


def snap_result(jev_cuts, split_cuts, *, mid_sentence=0, source='s' * 64):
    summary = lambda name: dict(mid_sentence_cuts=mid_sentence if name == 'jev' else 0)
    return seal(dict(source_sha256=source, arms=dict(original=[len(BLOCK0) + 2], code=jev_cuts, jev=jev_cuts, jev_split=split_cuts),
                     summaries=dict(jev=summary('jev'), jev_split=summary('jev_split')),
                     placement=dict(guard_violations=0, dropped_edges=[])))


class World(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        build_world(self.root)
        self.out = self.root / 'out'
        self.original = stage.paths
        stage.paths = lambda base: (self.root / 'leaf.json', self.root / 'slice.json', self.out)
        self.addCleanup(lambda: setattr(stage, 'paths', self.original))
        self.arms_dir = self.out / 'arms-281'

    def write_snap(self, **kwargs):
        cuts = [after('First line sentence one.'), after('goes here.')]
        both = sorted(cuts + [after('First line sentence two here.')])
        write_json(self.arms_dir / 'snap_result.json', snap_result(cuts, both, **kwargs))


class SnapVideoTests(World):
    def test_a_video_run_uses_its_own_folder_and_ledger_and_leaves_the_held_out_artifacts_alone(self):
        from types import SimpleNamespace
        sentences = lambda tag: ' '.join(f'This is sentence number {i} of the {tag} block.' for i in range(1, 7))
        blocks = [dict(coordinate=f'v281b{10 + i}', block_id=10 + i, text=sentences(i), start_seconds=60.0 * i, end_seconds=60.0 * i + 59,
                       segment_indexes=[i], ordinal=i, signals={}) for i in range(3)]
        write_json(self.root / 'leaf.json', dict(sermons=[dict(video_id=281, title='S', url='https://youtu.be/x', source_sha256='s' * 64, blocks=blocks)]))
        calls = []

        class Client:
            def system_one(self, state, questions, *, model=None, timeout=None):
                calls.append(len(questions))
                return SimpleNamespace(nouls={k: SimpleNamespace(noul=0.6) for k in questions}, usage=SimpleNamespace(input_tokens=1000), model=model)

        factory = lambda model: (Client(), lambda **kwargs: kwargs)
        plan = snap.run(self.root, check_only=True, video=281)
        self.assertEqual((281, []), (plan['video_id'], calls))
        done = snap.run(self.root, factory=factory, state=CLEAN, video=281)
        self.assertTrue((self.arms_dir / 'snap_result.json').exists())
        self.assertFalse((self.arms_dir / 'snap_sample.json').exists())      # no blind packet for the downstream comparison
        self.assertFalse((self.out / 'snap_result.json').exists())           # sermon 1200's result is untouched
        self.assertTrue(all(s['coverage']['ok'] for s in done['summaries'].values()))
        ledger = read_json(self.arms_dir / 'ledger.json')
        self.assertEqual(('1.00', 600), (ledger['ceiling_usd'], ledger['ceiling_attempts']))
        self.assertTrue(all(key.startswith('leaf/snap/') for key in ledger['entries']))


class FlagRuleTests(unittest.TestCase):
    def test_pairs_need_the_topic_at_0_9_and_leaves_at_0_8_and_keep_the_top_two_by_probability(self):
        units = [dict(id='u1'), dict(id='u2'), dict(id='u3')]
        signals = {'u1': SIGNALS, 'u2': {**SIGNALS, 'T:society_public_life': 0.89}, 'u3': {'T:society_public_life': 1.0, 'P:critical': 0.79}}
        pairs = arms.flagged_pairs(units, signals)
        self.assertEqual([('u1', 'P:critical'), ('u1', 'P:moral')], [(p['unit'], p['leaf']) for p in pairs])  # theological 0.82 is the third


class UnitTests(World):
    def test_arms_cover_the_text_share_a_line_cut_mid_line_and_keep_a_whole_block_exact(self):
        self.write_snap()
        built = arms.build_units(self.root, check_only=True)
        self.assertEqual(dict(b=2, s=3, x=4), built['units'])
        self.assertTrue(built['a1']['passed'])
        self.assertEqual(dict(b=0, s=1, x=1), built['lines_shared_between_units'])   # a cut inside a line shares its segments
        self.assertFalse((self.arms_dir / 'units.json').exists())
        arms.build_units(self.root)
        units = arms.load_units(self.root)['units']
        self.assertEqual([0, 1, 2], units['s'][1]['segment_indexes'])
        self.assertEqual((0.0, 29.0), (units['s'][0]['start_seconds'], units['s'][1]['end_seconds']))
        whole = units['s'][2]
        self.assertEqual('v281b11', whole['whole_block'])
        self.assertEqual((30.0, 40.0, [3]), (whole['start_seconds'], whole['end_seconds'], whole['segment_indexes']))  # the saved block's own values
        self.assertEqual(BLOCK1, whole['text'])

    def test_a_mid_sentence_cut_or_wrong_source_fails_integrity_and_stops_the_run(self):
        self.write_snap(mid_sentence=1)
        arms.build_units(self.root)
        with self.assertRaises(ValueError):
            arms.load_units(self.root)
        self.write_snap(source='x' * 64)
        with self.assertRaises(ValueError):
            arms.build_units(self.root)

    def test_a_unit_that_overlaps_no_caption_line_is_unmapped(self):
        source = arms.load_source(self.root)
        rows, _ = arms.line_table(source)
        self.assertIsNone(arms.map_unit(rows, source['segments'], len(TEXT) + 5, len(TEXT) + 9))

    def test_misaligned_blocks_become_one_line_with_all_their_segments(self):
        source = arms.load_source(self.root)
        source['class_blocks'][10]['normalization']['normalized_units'] = [dict(source_segment_indexes=[0])]
        rows, misaligned = arms.line_table(source)
        self.assertEqual(['v281b10'], misaligned)
        self.assertEqual([0, 1, 2], rows[0]['sources'])

    def test_saved_pilot_answers_are_reused_only_when_the_whole_identity_is_identical(self):
        self.write_snap()
        arms.build_units(self.root)
        source, built = arms.load_source(self.root), arms.load_units(self.root)['units']['b']
        blocks, contexts = arms.transcript_blocks(built, source['segments'])
        cache = TypeSafeBlockCache(self.root / 'new-cache', model='jev-1.13.0')
        pilot = TypeSafeBlockCache(self.root / 'pilot-cache', model='jev-1.13.0')
        for pack in arms.PACKS['T'][0], arms.PACKS['P'][0]:
            identity = cache._pack_identity({}, blocks[0], pack=pack, role_context=None, topic_context=contexts[blocks[0].block_id])
            if pack == arms.PACKS['T'][0]:   # the pilot's topic answers sit under the earlier transport identity
                identity = dict(identity, questions=topic_question_inventory(0))
            pilot._write_pack(pilot._pack_path(pack, identity), identity, dict(answer='x'), count_miss=False)
        count = arms.seed_from_pilot(cache, pilot.root, blocks, contexts, 'TP', copy=False)
        self.assertEqual((2, 2), (count['reusable'], count['missing']))
        self.assertFalse((self.root / 'new-cache').exists())     # a check copies nothing
        arms.seed_from_pilot(cache, pilot.root, blocks, contexts, 'TP', copy=True)
        self.assertEqual(2, len(list((cache.root / 'packs').rglob('*.json'))))
        self.assertEqual(2, arms.seed_from_pilot(cache, pilot.root, blocks, contexts, 'TP', copy=False)['already_here'])


def write_assessment(root, arm, signals):
    units = arms.load_units(root)['units'][arm]
    write_json(root_path(root) / f'assess_{arm}.json', seal(dict(arm=arm, units=[dict(id=u['id'], signals=signals(u)) for u in units])))


def root_path(root):
    return stage.paths(root)[2] / 'arms-281'


class Extracted(World):
    def setUp(self):
        super().setUp()
        self.write_snap()
        arms.build_units(self.root)
        for arm in ('s', 'x'):
            write_assessment(self.root, arm, lambda u: dict(SIGNALS) if u['start'] < len(BLOCK0) else dict(SIGNALS, **{'T:society_public_life': 0.1}))

    def reply(self, anchor, **changes):
        import json
        return json.dumps(dict(claims=[claim(anchor, area='public_life', object='the experiment', **changes)]))


class MainPointTests(Extracted):
    def test_the_instruction_allows_at_most_one_record_and_the_response_schema_is_unchanged(self):
        with self.assertRaises(main_point.SchemaError):
            main_point.validate(dict(claims=[claim('a'), claim('b')]))
        self.assertEqual([], main_point.validate(dict(claims=[])))
        self.assertIn('main point', main_point.SYSTEM_PROMPT)
        self.assertIn('"name":"P:critical"', main_point.user_message('P:critical', '', 'target', ''))

    def test_every_arm_is_asked_the_same_way_and_pairs_follow_the_frozen_flag_rule(self):
        counts = {arm: main_point.run(self.root, arm, check_only=True) for arm in arms.ARMS}
        self.assertEqual((2, 1), (counts['b']['pairs'], counts['b']['units_with_a_pair']))   # block 10 only; block 11's topic is 0.4
        self.assertEqual((4, 2), (counts['s']['pairs'], counts['s']['units_with_a_pair']))   # two units of block 10
        self.assertFalse((self.arms_dir / 'plan.json').exists())

    def test_run_records_anchor_positions_in_the_sermon_freezes_and_never_repeats_a_request(self):
        pair = main_point.pair_inputs(self.root, 'b')[0]
        anchor = 'Second line sentence three goes here.'
        calls, outputs = [], {p['key']: self.reply(anchor) for p in main_point.pair_inputs(self.root, 'b')}
        done = main_point.run(self.root, 'b', transport=stream_transport(outputs, calls), state=CLEAN, metadata=METADATA)
        self.assertEqual((2, 2, None), (done['summary']['records'], done['summary']['ok'], done['stopped']))
        result = read_json(self.arms_dir / 'extraction_b.json')
        record = result['rows'][0]['claims'][0]
        self.assertEqual(anchor, TEXT[record['sermon_start']:record['sermon_end']])
        self.assertEqual(TEXT.index(anchor), record['sermon_start'])
        self.assertTrue((self.arms_dir / 'plan.json').exists())
        main_point.run(self.root, 'b', transport=stream_transport(outputs, calls), state=CLEAN, metadata=METADATA)
        self.assertEqual(2, len(calls))                      # receipts stand; no retry
        self.assertEqual(pair['key'], f"b001-{pair['leaf'].removeprefix('P:')}")

    def test_one_transport_failure_in_a_small_arm_is_recorded_but_does_not_stop_it(self):
        pairs = main_point.pair_inputs(self.root, 'b')
        outputs = {p['key']: self.reply('Second line sentence three goes here.') for p in pairs}
        outputs[pairs[0]['key']] = ValueError('network')
        done = main_point.run(self.root, 'b', transport=stream_transport(outputs), state=CLEAN, metadata=METADATA)
        self.assertEqual((1, 1, None), (done['summary']['transport_failures'], done['summary']['ok'], done['stopped']))
        outputs[pairs[1]['key']] = ValueError('network')
        again = main_point.run(self.root, 's', transport=stream_transport({p['key']: ValueError('network') for p in main_point.pair_inputs(self.root, 's')}),
                               state=CLEAN, metadata=METADATA)
        self.assertIn('transport failures', again['stopped'])    # two or more, and over 5%
        self.assertEqual(2, again['summary']['attempted'])       # it stopped as soon as the floor was reached

    def test_a_dirty_tree_and_a_changed_instruction_are_refused(self):
        with self.assertRaises(ValueError):
            main_point.run(self.root, 'b', state=DIRTY, metadata=METADATA)
        outputs = {p['key']: self.reply('Second line sentence three goes here.') for p in main_point.pair_inputs(self.root, 'b')}
        main_point.run(self.root, 'b', transport=stream_transport(outputs), state=CLEAN, metadata=METADATA)
        original = main_point.SYSTEM_PROMPT
        self.addCleanup(lambda: setattr(main_point, 'SYSTEM_PROMPT', original))
        main_point.SYSTEM_PROMPT = original + ' Also be brief.'
        with self.assertRaises(ValueError):
            main_point.run(self.root, 's', state=CLEAN, metadata=METADATA)

    def test_a_record_whose_anchor_is_not_in_the_unit_is_an_anchor_failure_and_schema_failures_stop_the_arm(self):
        pairs = main_point.pair_inputs(self.root, 'b')
        outputs = {p['key']: self.reply('Words that are not in the sermon at all.') for p in pairs}
        done = main_point.run(self.root, 'b', transport=stream_transport(outputs), state=CLEAN, metadata=METADATA)
        self.assertEqual((0, 2), (done['summary']['records'], done['summary']['anchor_failures']))
        for item in pairs:
            outputs[item['key']] = '{"claims": "no"}'
        again = main_point.run(self.root, 's', transport=stream_transport({p['key']: '{"claims": "no"}' for p in main_point.pair_inputs(self.root, 's')}),
                               state=CLEAN, metadata=METADATA)
        self.assertIn('schema failures', again['stopped'])


class ReviewTests(Extracted):
    def extract_all(self):
        anchors = {'b': 'Second line sentence three goes here.', 's': 'Second line sentence three goes here.', 'x': 'First line sentence two here.'}
        for arm in arms.ARMS:
            pairs = main_point.pair_inputs(self.root, arm)
            only = [p for p in pairs if TEXT.index(anchors[arm]) >= p['unit_start'] and TEXT.index(anchors[arm]) < p['unit_start'] + len(p['text'])]
            outputs = {p['key']: self.reply(anchors[arm]) for p in only}
            outputs.update({p['key']: '{"claims": []}' for p in pairs if p not in only})
            main_point.run(self.root, arm, transport=stream_transport(outputs), state=CLEAN, metadata=METADATA)

    def test_the_queue_is_blind_labels_a_shared_record_once_and_resumes(self):
        self.extract_all()
        built = arms_review.build_queue(self.root)
        queue = read_json(self.arms_dir / 'review.json')
        self.assertEqual(built['items'], queue['item_count'])
        self.assertEqual(2, queue['item_count'])             # b and s share one record; x has its own
        self.assertEqual(1, built['shared_across_arms'])
        self.assertTrue(all(set(item) == {'id', 'watch_url', 'before', 'anchor', 'after', 'record', 'components'} for item in queue['items']))   # no arm
        mapping = read_json(self.arms_dir / 'review_arms.json')
        shared = [key for key, row in mapping['records'].items() if len(row['arms']) == 2]
        self.assertEqual(1, len(shared))
        self.assertEqual(['b', 's'], mapping['records'][shared[0]]['arms'])
        answers = iter(['a', 'r:proposition'])
        arms_review.interactive(self.root, lambda prompt: next(answers), lambda text: None)
        self.assertEqual(0, arms_review.progress(self.root)['remaining'])
        self.assertEqual({'accept', 'reject:proposition'}, {d['decision'] for d in arms_review.load_decisions(self.root).values()})

    def test_component_records_are_queued_and_judged_for_faithfulness_and_the_qualification(self):
        for arm in arms.ARMS:
            pairs = main_point.pair_inputs(self.root, arm)
            outputs = {p['key']: '{"claims": []}' for p in pairs}
            main_point.run(self.root, arm, transport=stream_transport(outputs), state=CLEAN, metadata=METADATA)
        item = dict(claim=claim('x'), sermon_start=TEXT.index('is working brilliantly'), sermon_end=TEXT.index('is working brilliantly') + 22)
        sermon = arms_review.sermons.load(self.root / 'leaf.json', 281)
        self.assertEqual([1], arms_review.component_candidates(sermon, item['sermon_start'], item['sermon_end']))
        self.assertEqual([], arms_review.component_candidates(sermon, 0, 10))


class AcceptanceTests(unittest.TestCase):
    def measures(self, shares, components=(5, 5, 5), qualified=(True, True, True), costs=(1.0, 1.0, 1.4), a1=True):
        row = lambda i, name: dict(accepted_share=shares[i], components_present=list(range(components[i])), qualification_attached=qualified[i],
                                   cost_per_accepted_usd=costs[i])
        return dict(a1=dict(passed=a1), arms={name: row(i, name) for i, name in enumerate(arms.ARMS)})

    def test_x_is_carried_forward_only_when_every_bar_holds(self):
        won = arms_review.evaluate(self.measures((0.6, 0.6, 0.7)))
        self.assertEqual('X (snapped edges with splitting)', won['decision'])
        self.assertEqual('S (snapped edges, no splitting)', arms_review.evaluate(self.measures((0.6, 0.6, 0.69)))['decision'])    # +0.09 is not a gain
        self.assertEqual('S (snapped edges, no splitting)', arms_review.evaluate(self.measures((0.6, 0.6, 0.8), costs=(1, 1, 1.6)))['decision'])
        self.assertEqual('S (snapped edges, no splitting)', arms_review.evaluate(self.measures((0.6, 0.6, 0.8), components=(5, 5, 4)))['decision'])
        self.assertEqual('S (snapped edges, no splitting)', arms_review.evaluate(self.measures((0.6, 0.6, 0.8), qualified=(True, True, False)))['decision'])

    def test_time_blocks_stay_when_snapping_is_worse_than_the_control_and_integrity_failure_stops_everything(self):
        self.assertEqual('time blocks stay', arms_review.evaluate(self.measures((0.7, 0.59, 0.9)))['decision'])   # 0.11 below the control
        self.assertEqual('S (snapped edges, no splitting)', arms_review.evaluate(self.measures((0.7, 0.6, 0.65)))['decision'])    # exactly 0.10 below the control is allowed
        self.assertEqual('time blocks stay', arms_review.evaluate(self.measures((0.6, 0.6, 0.9), components=(5, 4, 5)))['decision'])
        self.assertEqual('stopped: A1 failed', arms_review.evaluate(self.measures((0.6, 0.9, 0.9), a1=False))['decision'])


if __name__ == '__main__':
    unittest.main()
