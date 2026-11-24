from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest

from pastor_transcript_extractor.bound_claims.common import read_json, write_json
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger
from pastor_transcript_extractor.thought_units import candidates as cand, decide, improve, jev, questions, snap, stage

try:
    from tests.bound_claims_support import CLEAN, DIRTY
except ImportError:
    from bound_claims_support import CLEAN, DIRTY

TEXT = ('We began with a long introduction here today. It was a good opening for everyone present. Now this is a new subject entirely. '
        'It has several parts to consider carefully. We have to conclude that the experiment.\nExcuse me for a second here. I am sorry about that '
        'right now. We have to conclude it works brilliantly in practice. It has succeeded beyond all our wildest dreams. wildest dreams. '
        'Now here we turn to something else completely. It concerns the people and their government today.')


def words_of(text, piece):
    return text[piece.start:piece.end]


class CandidateTests(unittest.TestCase):
    def test_pieces_merge_a_repeated_tail_and_keep_the_text_literal(self):
        pieces = cand.split_pieces(TEXT)
        texts = [words_of(TEXT, p) for p in pieces]
        self.assertIn('It has succeeded beyond all our wildest dreams. wildest dreams.', texts)
        self.assertEqual(TEXT.count('wildest dreams.'), 2)  # nothing was edited

    def test_candidates_need_four_words_on_each_side_and_windows_quote_three_sentences(self):
        pieces = cand.split_pieces(TEXT)
        found = cand.candidates(TEXT, pieces)
        short = [i for i, p in enumerate(pieces) if len(cand.words(words_of(TEXT, p))) < 4]
        self.assertTrue(all(c.index not in short and c.index + 1 not in short for c in found))
        index = next(i for i, p in enumerate(pieces) if words_of(TEXT, p).startswith('We have to conclude that'))
        before, between, after = cand.passages(TEXT, pieces, index, 2)
        self.assertEqual(['Excuse me for a second here. I am sorry about that right now.'], [between])
        self.assertTrue(after.startswith('We have to conclude it works') and before.endswith('the experiment.'))
        self.assertEqual(3, before.count('.'))

    def test_a_long_stretch_without_punctuation_gets_line_candidates(self):
        long_text = '\n'.join(' '.join(['word'] * 7) + str(i) for i in range(12))  # 84 words, no sentence end
        pieces = cand.split_pieces(long_text)
        self.assertEqual(12, len(pieces))
        self.assertEqual(11, len(cand.candidates(long_text, pieces)))


class DecideTests(unittest.TestCase):
    def test_truth_table_has_an_outcome_for_every_combination(self):
        grid = [0.0, 0.3, 0.5, 0.7, 1.0]
        seen = {decide.outcome(a, b) for a in grid for b in grid}
        self.assertEqual({'cut', 'no_cut', 'unsettled'}, seen)
        self.assertEqual('cut', decide.outcome(0.2, 0.9))
        self.assertEqual('no_cut', decide.outcome(0.8, 0.9))
        self.assertEqual('no_cut', decide.outcome(0.2, 0.2))
        self.assertEqual('unsettled', decide.outcome(0.5, 0.5))

    def test_resumption_uses_the_smallest_skip_and_reports_unsettled_and_break(self):
        self.assertEqual(('aside', 2), decide.resumption({1: 0.1, 2: 0.8, 3: 0.9}))
        self.assertEqual(('unsettled', None), decide.resumption({1: 0.1, 2: 0.5}))
        self.assertEqual(('break', None), decide.resumption({1: 0.1, 2: 0.2}))

    def units(self, outcomes, asides=None, q2=None):
        pieces = cand.split_pieces(TEXT)
        found = cand.candidates(TEXT, pieces)
        full = {c.index: outcomes.get(c.index, 'no_cut') for c in found}
        return pieces, found, decide.build_units(len(pieces), pieces, found, q2 or {c.index: 0.5 for c in found}, full, asides or {})

    def test_cuts_split_units_and_an_aside_merges_across_its_boundaries(self):
        pieces = cand.split_pieces(TEXT)
        found = cand.candidates(TEXT, pieces)
        aside_at = next(i for i, p in enumerate(pieces) if words_of(TEXT, p).startswith('We have to conclude that'))
        cuts = {c.index: 'cut' for c in found if c.index in {2, aside_at, aside_at + 1, aside_at + 2}}
        _, _, plain = self.units(cuts)
        _, _, merged = self.units(cuts, asides={aside_at: 2})
        self.assertGreater(len(plain), len(merged))
        unit = next(u for u in merged if u.first <= aside_at <= u.last)
        self.assertGreaterEqual(unit.last, aside_at + 3)
        self.assertEqual([(aside_at + 1, aside_at + 2)], unit.asides)

    def test_oversize_units_split_at_the_highest_q2_and_undersize_units_merge(self):
        pieces = [cand.Piece(i * 100, i * 100 + 90) for i in range(40)]
        found = [cand.Candidate(i, pieces[i].end) for i in range(39)]
        q2 = {c.index: (0.9 if c.index == 17 else 0.5) for c in found}
        units = decide.build_units(40, pieces, found, q2, {c.index: 'no_cut' for c in found}, {})
        self.assertTrue(all(pieces[u.last].end - pieces[u.first].start <= decide.MAX_UNIT_CHARACTERS for u in units))
        self.assertIn(17, [u.last for u in units])
        lone = decide.build_units(6, pieces[:6], found[:5], {i: 0.5 for i in range(5)}, {0: 'cut', 1: 'cut', 2: 'cut', 3: 'cut', 4: 'cut'}, {})
        self.assertTrue(all(u.last - u.first + 1 >= decide.MIN_UNIT_PIECES for u in lone))


class FakeClient:
    def __init__(self, answer, calls):
        self.answer, self.calls = answer, calls

    def system_one(self, state, questions_, *, model=None, timeout=None):
        self.calls.append(sorted(questions_))
        nouls = {key: SimpleNamespace(noul=self.answer(key, spec)) for key, spec in questions_.items()}
        return SimpleNamespace(nouls=nouls, usage=SimpleNamespace(input_tokens=2000), model=model)


def factory_for(answer, calls):
    return lambda model: (FakeClient(answer, calls), lambda **kwargs: kwargs)


def answer(key, spec):
    instructions = spec['instructions']
    if 'resumes' in instructions['statement_to_evaluate']:
        return 0.9 if 'Excuse me' in instructions.get('text_between_the_passages', '') else 0.1
    if 'mid-sentence' in instructions['statement_to_evaluate'] or 'middle of a sentence' in instructions['statement_to_evaluate']:
        return 0.1
    return 0.9 if instructions['second_passage'].startswith('Now') else 0.1


class DisplayTests(unittest.TestCase):
    def test_review_windows_end_at_whole_sentences(self):
        pieces = cand.split_pieces(TEXT)
        position = next(p.end for p in pieces if words_of(TEXT, p).startswith('We have to conclude that'))
        before = stage.snap_window(TEXT, pieces, position, before=True)
        after = stage.snap_window(TEXT, pieces, position, before=False)
        self.assertTrue(before.startswith(('We ', 'It ', 'Now ')) and before.rstrip().endswith('.'))
        self.assertTrue(after.lstrip().startswith('Excuse') and after.rstrip().endswith('.'))
        self.assertLessEqual(len(before), stage.DISPLAY)
        self.assertLessEqual(len(after), stage.DISPLAY)


class ImproveTests(unittest.TestCase):
    def test_atomic_rule_needs_closure_a_new_step_signal_and_no_development(self):
        base = dict(b1_transition=0.9, b2_new_element=0.1, b3_kind_of_speech=0.1, b4_closure=0.9, b5_development=0.1)
        self.assertEqual('cut', improve.atomic_outcome(base)[0])
        self.assertEqual('no_cut', improve.atomic_outcome({**base, 'b5_development': 0.8})[0])
        self.assertEqual('no_cut', improve.atomic_outcome({**base, 'b4_closure': 0.2})[0])
        self.assertEqual('unsettled', improve.atomic_outcome({**base, 'b1_transition': 0.2})[0])

    def test_graded_rule_uses_the_two_lowest_levels(self):
        self.assertEqual('cut', improve.graded_outcome({'1': 0.4, '2': 0.4, '3': 0.2})[0])
        self.assertEqual('no_cut', improve.graded_outcome({'4': 0.6, '5': 0.3, '2': 0.1})[0])
        self.assertEqual('unsettled', improve.graded_outcome({'2': 0.5, '4': 0.5})[0])

    def test_metrics_auc_and_the_adoption_rule(self):
        labels = {'a': True, 'b': True, 'c': False, 'd': False, 'e': None}
        decided = {'a': ('cut', 0.9), 'b': ('unsettled', 0.5), 'c': ('cut', 0.8), 'd': ('no_cut', 0.1), 'e': ('cut', 0.9)}
        scored = improve.metrics(labels, decided)
        self.assertEqual((4, 1, 1, 1), (scored['labeled'], scored['true_cuts'], scored['false_cuts'], scored['missed']))
        self.assertEqual((0.5, 0.5, 0.5), (scored['precision'], scored['recall'], scored['f1']))
        self.assertEqual(0.75, scored['auc'])
        results = {'base': dict(f1=0.4, precision=0.9, auc=0.6), 'wide': dict(f1=0.6, precision=0.9, auc=0.7),
                   'atomic': dict(f1=0.8, precision=0.7, auc=0.9), 'graded': dict(f1=0.5, precision=1.0, auc=0.8)}
        verdict = improve.verdict(results)
        self.assertEqual({'wide': True, 'atomic': False, 'graded': False}, verdict['improved'])
        self.assertEqual('wide', verdict['best'])

    def test_questions_cover_every_pair_and_approach_with_score_questions_marked(self):
        text = TEXT
        sermon = SimpleNamespace(text=text)
        items = [dict(id='i1', index=7), dict(id='i2', index=8)]
        built = improve.build_questions(sermon, items, 'q2a')
        self.assertEqual(2 * (2 + len(questions.ATOMIC) + 1), len(built))
        self.assertEqual('score', built['graded/i1']['kind'])
        self.assertNotEqual(built['base/i1']['instructions']['first_passage'], built['wide/i1']['instructions']['first_passage'])

    def test_score_answers_are_cached_as_level_probabilities(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)

        class ScoreClient:
            def system_one(self, state, questions_, *, model=None, timeout=None):
                scores = {k: SimpleNamespace(probabilities={1: 0.1, 2: 0.7, 3: 0.2}) for k in questions_}
                return SimpleNamespace(nouls={}, scores=scores, usage=SimpleNamespace(input_tokens=100))
        asker = jev.Asker(root / 'a.json', PilotLedger(root / 'l.json'), questions.STATE,
                          factory=lambda model: (ScoreClient(), dict(noul=lambda **kw: kw, score=lambda **kw: kw)))
        answer_ = asker.ask({'g': questions.graded('before text here', 'after text here')})
        self.assertEqual({'1': 0.1, '2': 0.7, '3': 0.2}, answer_['g'])


SNAP_TEXT = ' '.join(f'This is sentence number {i} in the sermon text today.' for i in range(40))


def snap_fixture():
    pieces = cand.split_pieces(SNAP_TEXT)
    found = cand.candidates(SNAP_TEXT, pieces)
    return pieces, found


class SnapTests(unittest.TestCase):
    def setUp(self):
        self.pieces, self.found = snap_fixture()
        self.edges = [pieces_end for pieces_end in (self.pieces[9].end + 12, self.pieces[19].end + 12, self.pieces[29].end + 12)]  # mid-sentence edges

    def test_units_partition_the_text_and_the_check_catches_a_loss(self):
        ranges = snap.ranges_from_cuts(SNAP_TEXT, [self.pieces[9].end, self.pieces[19].end])
        self.assertTrue(snap.coverage(SNAP_TEXT, ranges)['ok'])
        self.assertEqual(3, len(ranges))
        self.assertFalse(snap.coverage(SNAP_TEXT, [ranges[0], ranges[2]])['ok'])  # a dropped unit is detected
        self.assertTrue(snap.is_mid_sentence(SNAP_TEXT, self.edges[0]))
        self.assertFalse(snap.is_mid_sentence(SNAP_TEXT, self.pieces[9].end))

    def test_code_snap_moves_each_edge_to_the_nearest_sentence_end(self):
        cuts = snap.code_cuts(self.found, self.edges)
        self.assertTrue(all(not snap.is_mid_sentence(SNAP_TEXT, c) for c in cuts))
        self.assertEqual(self.pieces[9].end, cuts[0])

    def test_jev_edge_stays_at_the_nearest_sentence_end_unless_a_candidate_beats_it_by_the_margin(self):
        flat = {c.index: 0.4 for c in self.found}
        placed = snap.place_edges(SNAP_TEXT, self.pieces, self.found, flat, self.edges)
        self.assertEqual(snap.code_cuts(self.found, self.edges), placed['cuts'])
        self.assertEqual(0, sum(m['moved_off_nearest'] for m in placed['moves']))
        slight = {**flat, 7: 0.4 + snap.GAIN_MARGIN - 0.01}
        self.assertEqual(snap.code_cuts(self.found, self.edges), snap.place_edges(SNAP_TEXT, self.pieces, self.found, slight, self.edges)['cuts'])
        better = {**flat, 7: 0.4 + snap.GAIN_MARGIN + 0.01}
        moved = snap.place_edges(SNAP_TEXT, self.pieces, self.found, better, self.edges)
        self.assertIn(self.pieces[7].end, moved['cuts'])
        self.assertEqual(1, sum(m['moved_off_nearest'] for m in moved['moves']))

    def test_edges_stay_ordered_respect_the_guards_and_resolve_conflicts(self):
        everything_wants_one_place = {c.index: (0.9 if c.index == 14 else 0.1) for c in self.found}
        result = snap.place_edges(SNAP_TEXT, self.pieces, self.found, everything_wants_one_place, self.edges)
        self.assertEqual(sorted(result['cuts']), result['cuts'])
        self.assertEqual(len(set(result['cuts'])), len(result['cuts']))
        self.assertEqual(0, result['guard_violations'])
        ranges = snap.ranges_from_cuts(SNAP_TEXT, result['cuts'])
        self.assertTrue(all(snap.piece_count(self.pieces, a, b) >= snap.MIN_PIECES for a, b in ranges))
        self.assertTrue(snap.coverage(SNAP_TEXT, ranges)['ok'])

    def test_joint_placement_keeps_every_edge_when_scores_are_arbitrary(self):
        import hashlib
        scores = {c.index: int(hashlib.sha256(str(c.index).encode()).hexdigest()[:6], 16) / 0xFFFFFF for c in self.found}
        result = snap.place_edges(SNAP_TEXT, self.pieces, self.found, scores, self.edges)
        self.assertEqual(([], 0), (result['dropped_edges'], result['guard_violations']))
        self.assertEqual(len(self.edges), len(result['cuts']))
        self.assertTrue(snap.coverage(SNAP_TEXT, snap.ranges_from_cuts(SNAP_TEXT, result['cuts']))['ok'])

    def test_split_takes_ranked_local_peaks_at_least_three_sentences_apart(self):
        scores = {c.index: 0.2 + 0.0001 * c.index for c in self.found}   # no plateaus
        scores.update({5: 0.9, 6: 0.85, 20: 0.8, 33: 0.95})
        cuts = [self.pieces[12].end]
        result = snap.split_cuts(SNAP_TEXT, self.pieces, self.found, scores, cuts)
        added = {SNAP_TEXT[:p].count('sentence number') - 1 for p in result['added']}
        self.assertIn(5, added)
        self.assertNotIn(6, added)  # a neighbour of the stronger peak
        self.assertIn(33, added)
        self.assertIn(20, added)
        positions = sorted(result['cuts'])
        units = snap.ranges_from_cuts(SNAP_TEXT, positions)
        self.assertTrue(all(snap.piece_count(self.pieces, a, b) >= snap.MIN_PIECES for a, b in units))
        self.assertTrue(all(snap.piece_count(self.pieces, a, b) >= snap.SPLIT_SEPARATION for a, b in units[1:-1]))

    def test_judging_resumes_and_the_report_scores_the_bars(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        out = Path(directory.name)
        items = [dict(id=f'e{i}', kind='edge_pair', edge=0, versus='original' if i <= 6 else 'code', arms=dict(A='jev', B='original' if i <= 6 else 'code'), excerpt='x')
                 for i in range(1, 13)]
        items += [dict(id='s1', kind='split', position=5, arm='jev_split', excerpt='x'), dict(id='s2', kind='split', position=9, arm='jev_split', excerpt='x'),
                  dict(id='u1', kind='unit', arm='jev', start=0, end=5, excerpt='x'), dict(id='u2', kind='unit', arm='jev', start=5, end=9, excerpt='x'),
                  dict(id='u3', kind='unit', arm='jev_split', start=0, end=2, excerpt='x'), dict(id='u4', kind='unit', arm='jev_split', start=2, end=5, excerpt='x')]
        write_json(out / 'snap_sample.json', dict(items=items))
        summary = dict(mid_sentence_cuts=0, cuts=3)
        write_json(out / 'snap_result.json', dict(summaries=dict(jev=summary), placement=dict(guard_violations=0, moves=[dict(edge=0, candidates=5)])))
        answers = iter(['x'] + ['a'] * 5)
        snap.judge(out, 'brian', ('edge_pair',), 5, lambda prompt: next(answers), lambda text: None)
        resumed = snap.judge(out, 'brian', ('edge_pair',), 5, lambda prompt: self.fail('must not ask again'), lambda text: None)
        self.assertEqual(5, len(resumed))
        snap.record(out, 'claude', {**{f'e{i}': 'a' for i in range(1, 11)}, 'e11': 'b', 'e12': 't', 's1': 'y', 's2': 'y', 'u1': 'y', 'u2': 'y', 'u3': 'n', 'u4': 'n'})
        with self.assertRaises(ValueError):
            snap.record(out, 'claude', {'s1': 'a'})
        outcome = snap.report(out, 'claude')
        self.assertEqual(dict(wins=6, losses=0, ties=0), {k: outcome['bars']['H1']['observed'][k] for k in ('wins', 'losses', 'ties')})
        self.assertEqual((4, 1, 1), tuple(outcome['bars']['H2']['observed'][k] for k in ('wins', 'losses', 'ties')))
        self.assertEqual('INCONCLUSIVE', outcome['verdict'])  # fewer than 15 non-ties on edges with 3+ candidates
        self.assertTrue(outcome['bars']['H4']['passed'])
        self.assertEqual(dict(items=5, same=5), outcome['brian_agreement'])


class JevTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def asker(self, calls, ceiling=None):
        ledger = PilotLedger(self.root / 'ledger.json', **({} if ceiling is None else dict(ceiling_attempts=ceiling)))
        return jev.Asker(self.root / 'answers.json', ledger, questions.STATE, factory=factory_for(answer, calls)), ledger

    def test_batches_cap_questions_cache_answers_and_account_usage(self):
        calls = []
        asker, ledger = self.asker(calls)
        many = {f'q{i}': questions.q2('q2a', f'before {i}', f'Now after {i}') for i in range(160)}
        self.assertEqual(3, len(jev.batches(many)))
        self.assertTrue(all(len(batch) <= jev.BATCH_QUESTIONS for batch in jev.batches(many)))
        first = asker.ask(many)
        self.assertEqual(3, len(calls))
        self.assertEqual(3, ledger.summary()['attempts'])
        self.assertEqual({0.9}, set(first.values()))
        again, _ = self.asker(calls)
        self.assertEqual(first, again.ask(many))
        self.assertEqual(3, len(calls))  # cache: no new request

    def test_missing_answers_raise_instead_of_guessing(self):
        asker, _ = self.asker([])
        asker.factory = lambda model: (SimpleNamespace(system_one=lambda *a, **k: SimpleNamespace(nouls={}, usage=SimpleNamespace(input_tokens=5))), lambda **kw: kw)
        with self.assertRaises(ValueError):
            asker.ask({'a': questions.q2('q2a', 'b', 'a')})

    def test_check_only_plan_sends_nothing(self):
        calls = []
        asker, _ = self.asker(calls)
        plan = asker.plan({'a': questions.q2('q2a', 'b', 'a')})
        self.assertEqual((1, 1, []), (plan['questions'], plan['requests'], calls))


def build_sermon_files(root):
    blocks = [dict(coordinate=f'v7b{i}', block_id=i, text=text, start_seconds=100.0 * i)
              for i, text in enumerate([TEXT[:TEXT.index('We have to conclude it works')].rstrip(), TEXT[TEXT.index('We have to conclude it works'):]])]
    write_json(root / 'leaf.json', dict(sermons=[dict(video_id=7, title='Sermon', url='https://youtu.be/x', source_sha256='s' * 64, blocks=blocks)]))
    source = dict(classification=dict(blocks=[dict(block_id=b['block_id'], text=b['text'], segment_indexes=[10 * b['block_id'], 10 * b['block_id'] + 1],
                                                    normalization=dict(normalized_units=[dict(source_segment_indexes=[10 * b['block_id']])] * len(b['text'].split('\n'))))
                                               for b in blocks]),
                  segments=[dict(start_seconds=float(i)) for i in range(40)])
    write_json(root / 'proposed.json', source)
    write_json(root / 'slice.json', dict(sermons=[dict(video_id=7, source_path=str(root / 'proposed.json'))]))


class StageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        build_sermon_files(self.root)
        self.out = self.root / 'out'
        self.original = stage.paths
        stage.paths = lambda base: (self.root / 'leaf.json', self.root / 'slice.json', self.out)
        self.addCleanup(lambda: setattr(stage, 'paths', self.original))
        write_json(self.out / 'probe_result.json', dict(selected=dict(q1='q1a', q2='q2a')))

    def run_segment(self, calls, **kwargs):
        return stage.segment(self.root, 7, factory=factory_for(answer, calls), state=kwargs.pop('state', CLEAN), **kwargs)

    def test_check_only_sends_nothing_and_writes_nothing_but_reports_the_plan(self):
        calls = []
        plan = self.run_segment(calls, check_only=True)
        self.assertEqual([], calls)
        self.assertGreater(plan['candidates'], 0)
        self.assertFalse((self.out / 'plan.json').exists())

    def test_segment_builds_units_with_an_aside_and_freezes_the_plan(self):
        calls = []
        done = self.run_segment(calls)
        result = read_json(self.out / 'units.json')
        self.assertEqual(done['units'], len(result['units']))
        self.assertGreaterEqual(result['resumption']['aside'], 1)
        merged = [u for u in result['units'] if u['asides']]
        self.assertTrue(any('Excuse me' in u['text'] and 'works brilliantly' in u['text'] for u in merged))
        self.assertTrue((self.out / 'plan.json').exists())
        self.assertIn('segment_index', result['units'][0]['location'])
        with self.assertRaises(ValueError):
            stage.freeze(self.out, dict(stage._identity(stage.sermons.load(self.root / 'leaf.json', 7), 'x', dict(q1='q1b', q2='q2a'))), CLEAN)

    def test_dirty_tree_is_refused_before_any_request(self):
        calls = []
        with self.assertRaises(ValueError):
            self.run_segment(calls, state=DIRTY)
        self.assertEqual([], calls)

    def test_probe_scoring_skips_ambiguous_pairs_and_ties_go_to_the_shortest_wording(self):
        answers = {}
        labels = {'p1': dict(mid_sentence=False, new_point=True), 'p2': dict(mid_sentence=False, new_point=False), 'p3': dict(mid_sentence=None, new_point=None)}
        for variant in list(questions.Q1_VARIANTS) + list(questions.Q2_VARIANTS):
            answers.update({f'{variant}/p1': 0.9, f'{variant}/p2': 0.1, f'{variant}/p3': 0.5})
        answers['q2b/p1'] = 0.5  # q2b misses the positive
        scored = stage.score_probe(answers, labels)
        self.assertEqual(2, scored['variants']['q2a']['pairs'])
        self.assertEqual(1.0, scored['variants']['q2a']['agreement'])
        self.assertEqual(0.5, scored['variants']['q2b']['agreement'])
        shortest = min(questions.Q1_VARIANTS, key=lambda v: len(questions.Q1_VARIANTS[v]['statement']))
        self.assertEqual(shortest, scored['selected']['q1'])

    def test_boundary_judging_resumes_and_the_gate_needs_80_percent(self):
        items = [dict(number=i, kind='boundary', before='b', after='a') for i in range(1, 6)] + [dict(number=6, kind='non_boundary', before='b', after='a')]
        write_json(self.out / 'g1_sample.json', dict(items=items))
        answers = iter(['maybe', 'y', 'y', 'y', 'y', 'n', 'n'])
        stage.judge(self.out, lambda prompt: next(answers), lambda text: None)
        resumed = stage.judge(self.out, lambda prompt: self.fail('must not ask again'), lambda text: None)
        self.assertEqual(6, len(resumed))
        report = stage.g1_report(self.out)
        self.assertEqual(('PASS', 6), (report['status'], report['boundary_positions']['judged']))
        write_json(self.out / 'g1_judgments.json', {str(i): False for i in range(1, 7)})
        self.assertEqual('FAIL', stage.g1_report(self.out)['status'])


if __name__ == '__main__':
    unittest.main()


class PublicSetSnapTests(unittest.TestCase):
    """Section 28 Stage 0b: the snap runs on public-set sermons through their own loader, folder and ledger."""

    def setUp(self):
        from unittest import mock
        from pastor_transcript_extractor.bound_claims.common import write_json
        from pastor_transcript_extractor.object_position import sermon as sermon_module
        from pastor_transcript_extractor.thought_units import public_set
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        pieces = cand.split_pieces(SNAP_TEXT)
        starts = [0, pieces[9].end + 12, pieces[19].end + 12, pieces[29].end + 12]
        ends = [*starts[1:], len(SNAP_TEXT)]
        blocks = tuple((f'b{i:04d}', a, b, 10.0 * i) for i, (a, b) in enumerate(zip(starts, ends)))
        self.loaded = []

        def load(base_dir, video_id, set_id='v1'):
            self.loaded.append((video_id, set_id))
            return sermon_module.Sermon(video_id=video_id, title='t', url='u', source_sha256='x', text=SNAP_TEXT, blocks=blocks)
        patcher = mock.patch.object(public_set, 'load_sermon', load)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.public_set = public_set
        folder = public_set.set_dir(self.base, 'v2')
        write_json(folder / public_set.pairs_name(3), dict(pairs=[dict(video_id=9, key='a'), dict(video_id=7, key='b'), dict(video_id=9, key='c')]))

    def test_only_sermons_with_pairs_are_snapped_in_video_order(self):
        self.assertEqual([7, 9], snap.pair_sermons(self.base, 'v2'))

    def test_check_only_totals_the_estimate_without_a_provider_and_keeps_a_folder_per_sermon(self):
        result = snap.run_pair_sermons(self.base, 'v2', check_only=True, factory=lambda model: self.fail('check-only must not call the provider'))
        self.assertEqual(2, result['sermons'])
        self.assertEqual(sorted(result['per_sermon']), ['7', '9'])
        self.assertEqual([(7, 'v2'), (9, 'v2')], self.loaded)
        self.assertGreater(result['requests'], 0)
        self.assertEqual(result['requests'], sum(v['requests'] for v in result['per_sermon'].values()))
        self.assertNotEqual(snap.set_snap_dir(self.base, 'v2', 7), snap.set_snap_dir(self.base, 'v2', 9))

    def test_a_set_snap_without_a_sermon_is_refused(self):
        with self.assertRaises(ValueError):
            snap.run(self.base, check_only=True, set_id='v2')


class Stage0Tests(unittest.TestCase):
    """Section 28 Stage 0: the target point of a pair is the span of its anchored block-run records, fixed from saved data."""

    def test_target_point_spans_anchored_records_and_is_none_without_one(self):
        from pastor_transcript_extractor.bound_claims.common import write_json
        from pastor_transcript_extractor.thought_units import public_set, stage0
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            folder = public_set.set_dir(base, 'v2')
            pair = lambda key, unit, leaf: dict(key=key, unit=unit, leaf=leaf, video_id=5, unit_start=100)
            claim = lambda a, b, status='ok': dict(sermon_start=a, sermon_end=b, anchor=dict(status=status))
            write_json(folder / public_set.pairs_name(3), dict(pairs=[pair('v5-b1-critical', 'b1', 'P:critical'), pair('v5-b2-moral', 'b2', 'P:moral'),
                                                                     pair('v5-b3-moral', 'b3', 'P:moral')]))
            # the second pair was excluded from the run for input size, so it has no row
            write_json(folder / stage0.EXTRACTION, dict(rows=[dict(unit='b1', leaf='P:critical', claims=[claim(110, 160), claim(300, 340)]),
                                                              dict(unit='b3', leaf='P:moral', claims=[claim(500, 520, 'failed')])]))
            table = stage0.target_points(base, 'v2')
            self.assertEqual(['v5-b1-critical', 'v5-b3-moral'], [row['key'] for row in table])
            self.assertEqual(dict(start=110, end=340), table[0]['point'])
            self.assertEqual((2, 2), (table[0]['records'], table[0]['anchored']))
            self.assertIsNone(table[1]['point'])


class Stage3Tests(unittest.TestCase):
    """Section 28.8: the matched record and where a block lies after the snap."""

    def setUp(self):
        from pastor_transcript_extractor.thought_units import stage3
        self.stage3 = stage3

    def claim(self, start, end):
        return dict(sermon_start=start, sermon_end=end)

    def test_matched_record_needs_half_of_the_shorter_span_and_takes_the_largest_overlap(self):
        point = dict(start=100, end=200)
        self.assertIsNone(self.stage3.matched_record([], point))
        self.assertIsNone(self.stage3.matched_record([self.claim(300, 350)], point))                       # elsewhere in the unit
        self.assertIsNone(self.stage3.matched_record([self.claim(190, 400)], point))                       # 10 of the shorter 100 characters
        self.assertEqual(self.claim(150, 180), self.stage3.matched_record([self.claim(150, 180)], point))   # inside the point: the whole shorter span overlaps
        both = [self.claim(95, 130), self.claim(120, 210)]
        self.assertEqual(self.claim(120, 210), self.stage3.matched_record(both, point))                     # 80 characters against 30
        tie = [self.claim(100, 130), self.claim(150, 180)]
        self.assertEqual(self.claim(100, 130), self.stage3.matched_record(tie, point))                      # the earlier record on a tie

    def test_block_range_follows_the_moved_edges_and_reports_a_merge(self):
        blocks = [('b0', 0, 100, 0.0), ('b1', 100, 200, 1.0), ('b2', 200, 300, 2.0)]
        result = dict(placement=dict(moves=[dict(edge=0, placed=110), dict(edge=1, placed=190)], dropped_edges=[]))
        self.assertEqual((0, 110), self.stage3.block_range(result, blocks, 0, 300))
        self.assertEqual((110, 190), self.stage3.block_range(result, blocks, 1, 300))
        self.assertEqual((190, 300), self.stage3.block_range(result, blocks, 2, 300))
        dropped = dict(placement=dict(moves=[dict(edge=0, placed=110)], dropped_edges=[1]))
        self.assertIsNone(self.stage3.block_range(dropped, blocks, 1, 300))                                  # an edge next to it was dropped
        self.assertIsNone(self.stage3.block_range(dropped, blocks, 2, 300))
        self.assertEqual((0, 110), self.stage3.block_range(dropped, blocks, 0, 300))


class PipelineArmsTests(unittest.TestCase):
    """Section 30: units cut from the sermon text carry the segments and times of the saved blocks they overlap."""

    def test_unit_records_take_segments_and_times_from_overlapped_blocks(self):
        from pastor_transcript_extractor.thought_units import pipeline_arms
        text = 'a' * 100
        originals = [dict(start=0, end=40, segment_indexes=[0, 1], start_seconds=0.0, end_seconds=30.0),
                     dict(start=42, end=100, segment_indexes=[2, 3], start_seconds=31.0, end_seconds=60.0)]
        records = pipeline_arms.unit_records(originals, [(0, 30), (30, 70), (70, 100)], text, 'u')
        self.assertEqual(['u0000', 'u0001', 'u0002'], [r['id'] for r in records])
        self.assertEqual([[0, 1], [0, 1, 2, 3], [2, 3]], [r['segment_indexes'] for r in records])
        self.assertEqual((0.0, 60.0), (records[1]['start_seconds'], records[1]['end_seconds']))
        self.assertEqual((70, 100, 30), (records[2]['start'], records[2]['end'], len(records[2]['text'])))
        self.assertEqual([0, 1, 2], [r['block_id'] for r in records])
        with self.assertRaises(ValueError):
            pipeline_arms.unit_records(originals[:1], [(50, 60)], text, 'u')


class WholeSermonTests(unittest.TestCase):
    def test_routing_follows_the_table(self):
        from pastor_transcript_extractor.thought_units import whole_sermon as w
        signals = {w.SALVATION_TOPIC: 0.6, w.PUBLIC_TOPIC: 0.54, 'T:ethics_moral_conduct': 0.7, 'T:scripture_revelation': 0.56, 'T:god_character_action': 0.4,
                   'S:atonement_as_basis': 0.7, 'S:forgiveness_pardon': 0.67, 'S:repentance_as_receiving_response': 0.99, 'P:moral': 0.95, 'L:serve': 0.8, 'L:give': 0.79}
        found = {(branch, leaf) for branch, leaf, _ in w.flagged(signals)}
        self.assertIn(('S', 'S:atonement_as_basis'), found)                       # at its own floor (.68)
        self.assertNotIn(('S', 'S:forgiveness_pardon'), found)                    # .67 is below its floor (.68)
        self.assertNotIn(('S', 'S:repentance_as_receiving_response'), found)      # unresolved leaves are scored, not extracted
        self.assertNotIn(('P', 'P:moral'), found)                                 # topic .54 is below the product route
        self.assertIn(('L', 'L:serve'), found)
        self.assertNotIn(('L', 'L:give'), found)
        self.assertEqual({leaf for branch, leaf, _ in w.flagged(signals) if branch == 'T'}, {'T:ethics_moral_conduct', 'T:scripture_revelation'})

    def test_every_extracted_leaf_has_its_own_meaning_and_the_public_life_ones_match_v4(self):
        from pastor_transcript_extractor.thought_units import main_point, whole_sermon as w
        for name in w.SALVATION_LEAVES:
            info = w.leaf_info(f'S:{name}')
            self.assertTrue(info['leaf_meaning'] and info['counts_when'] and info['does_not_count_when'] and info['category'] == 'salvation_gospel')
        for name in w.PUBLIC_LEAVES:
            self.assertEqual(w.leaf_info(f'P:{name}')['leaf_meaning'], main_point.leaf_meaning(f'P:{name}'))
        for name in w.DIRECTIVE_LEAVES:
            self.assertTrue(w.leaf_info(f'L:{name}')['leaf_meaning'])
        for name in w.OTHER_TOPICS:
            self.assertTrue(w.leaf_info(f'T:{name}')['leaf_meaning'])

    def test_the_v5_request_carries_what_jev_found_and_fits_the_cap(self):
        from pastor_transcript_extractor.thought_units import leaf_evidence as e, whole_sermon as w
        pair = dict(unit='u1', leaf='S:atonement_as_basis', branch='S', probability=0.9, video_id=1, unit_start=0, text='Christ died for our sins.', preceding_text='', following_text='',
                    key='v1-u1-S-atonement_as_basis', **w.leaf_info('S:atonement_as_basis'))
        message = json.loads(e.neutral_message(pair))
        self.assertEqual(set(message), {'category', 'leaf', 'preceding_unit', 'target_unit', 'following_unit'})
        self.assertIn('counts_when', message['leaf'])
        self.assertNotIn('probability', json.dumps(message))
        self.assertTrue(e.build_request(pair, e.V5, e.PRODUCER_32K).fingerprint)


class WholeRetryTests(unittest.TestCase):
    def _base(self, root):
        import tempfile  # noqa: F401
        from pastor_transcript_extractor.bound_claims.common import write_json
        from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
        from pastor_transcript_extractor.thought_units import arms, leaf_evidence as e, public_set
        pairs = [dict(unit=f'u{i % 3}', leaf='T:x', key=f'v{i}-u{i % 3}-T-x') for i in range(4)]    # unit ids repeat across sermons
        write_json(public_set.set_dir(root, 'v2') / 'whole' / 'pairs-u.json', seal(dict(pairs=pairs, pairs_sha256=arms.pairs_digest(pairs))))
        statuses = ['ok', 'transport_failure', 'schema_failure', 'transport_failure']
        rows = [dict(unit=p['unit'], leaf=p['leaf'], status=s, claims=[]) for p, s in zip(pairs, statuses)]
        write_json(e.leaf_dir(root, e.V5, e.WHOLE['u']) / 'extraction.json', dict(rows=rows))
        return e

    def test_retry_pairs_are_only_the_transport_failures_and_the_merge_replaces_only_them(self):
        import tempfile
        from pathlib import Path
        from pastor_transcript_extractor.bound_claims.common import write_json
        from pastor_transcript_extractor.thought_units import whole_sermon as w
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            e = self._base(root)
            built = w.build_retry_pairs(root, 'u')
            self.assertEqual(['v1-u1-T-x', 'v3-u0-T-x'], built['keys'])
            self.assertEqual(['transport_failure', 'schema_failure'], [r['status'] for r in w.merged_rows(root, 'u')][1:3])      # no retry output yet: unchanged
            write_json(w.extraction_path(root, e.WHOLE_RETRY['u']), dict(rows=[dict(unit='u1', leaf='T:x', status='ok', claims=[1]), dict(unit='u0', leaf='T:x', status='transport_failure', claims=[])]))
            merged = w.merged_rows(root, 'u')
            self.assertEqual(['ok', 'ok', 'schema_failure', 'transport_failure'], [r['status'] for r in merged])
            self.assertTrue(merged[1]['retry_of_transport_failure'] and merged[3]['retry_of_transport_failure'] and 'retry_of_transport_failure' not in merged[0])
            with self.assertRaises(ValueError):
                w.build_retry_pairs(root, 'b')

    def test_the_retry_ceiling_covers_fourteen_requests_and_stays_small(self):
        from pastor_transcript_extractor.thought_units import leaf_evidence as e
        scope = e.WHOLE_RETRY['u']
        self.assertGreaterEqual(scope.ceiling_attempts, 14)
        self.assertGreaterEqual(scope.ceiling_usd, 14 * e.provider.reserved_usd(e.PRODUCER_32K))
        self.assertLessEqual(scope.ceiling_attempts, 16)


class WholeAggregateTests(unittest.TestCase):
    def test_the_topic_mass_is_the_text_weighted_mean_and_names_are_filtered_by_prefix(self):
        from pastor_transcript_extractor.thought_units import whole_sermon as w
        units = [dict(id='a', text='x' * 30), dict(id='b', text='x' * 10)]
        signals = {'a': {'T:grace': 1.0, 'H:style': 0.2}, 'b': {'T:grace': 0.0, 'H:style': 0.6}}
        self.assertEqual({'T:grace': 0.75}, w._weighted(units, signals, 'T:'))
        self.assertEqual({'H:style': 0.3}, w._weighted(units, signals, 'H:'))


class WholeReportTests(unittest.TestCase):
    def test_unblinding_and_the_fixed_reading(self):
        import tempfile
        from pathlib import Path
        from pastor_transcript_extractor.bound_claims.common import write_json
        from pastor_transcript_extractor.thought_units import whole_sermon as w
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            here = w.report_dir(root)
            write_json(here / '_arm_codes_DO_NOT_SHARE.json', {str(v): {'b': 'K', 'u': 'M'} for v in w.VIDEOS})
            for video in w.VIDEOS:
                points = [dict(n=i, category='none' if i == 2 else 'god_character_action', K='partly', M='full', note='') for i in (1, 2)]
                write_json(here / f'judge_{video}.json', dict(control_points=points, K=dict(errors=['x'], closeness=3), M=dict(errors=[], closeness=4), better='M'))
                for code in 'KM':
                    (here / f'sum_{code}_{video}.txt').write_text('word ' * (410 if code == 'K' else 390))
                for arm in 'bu':
                    write_json(w.arm_dir(root, arm) / f'aggregate_v{video}.json', dict(extraction=dict(records=5, share_of_text_in_units_with_a_record=0.5, statuses={'ok': 5})))
            result = w.score_report(root)
            self.assertEqual('U (snapped units) closer', result['reading']['result'])      # gap 1.0 and more points fully conveyed
            self.assertEqual((0, 6, 0), (result['arms']['b']['full'], result['arms']['b']['partly'], result['arms']['b']['not_conveyed']))
            self.assertEqual(3, result['points_not_fully_conveyed']['outside_pipeline_categories']['b'])
            self.assertEqual(3, result['better_per_sermon']['u'])
            self.assertIn('closer', w.render_report(result))


class WholeCalibrationTests(unittest.TestCase):
    def test_ceiling_and_records_to_summary_crossing(self):
        import tempfile
        from pathlib import Path
        from pastor_transcript_extractor.bound_claims.common import write_json
        from pastor_transcript_extractor.thought_units import whole_sermon as w
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            here = w.report_dir(root)
            write_json(here / '_arm_codes_DO_NOT_SHARE.json', {str(v): {'b': 'K', 'u': 'M'} for v in w.VIDEOS})
            for video in w.VIDEOS:
                write_json(here / 'calibration' / f'judge3_{video}.json', dict(control_points=[dict(n=1, K='partly', M='not', C='full')],
                                                                              K=dict(errors=['x'], closeness=3), M=dict(errors=[], closeness=3), C=dict(errors=[], closeness=4)))
                write_json(here / 'calibration' / f'recall_{video}.json', dict(points=[dict(n=1, K='full', M='absent')]))
                write_json(here / f'judge_{video}.json', dict(control_points=[dict(n=1, K='partly', M='not')]))
            result = w.score_calibration(root)
            self.assertEqual((3, 4.0), (result['ceiling']['ceiling']['full'], result['ceiling']['ceiling']['mean_closeness']))
            self.assertEqual(3, result['ceiling']['b']['errors'])
            self.assertEqual({'records full -> summary partly': 3}, result['records_to_summary']['b'])
            self.assertEqual({'records absent -> summary not': 3}, result['records_to_summary']['u'])
