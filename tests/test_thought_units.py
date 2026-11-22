from pathlib import Path
from types import SimpleNamespace
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
