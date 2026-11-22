from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from pastor_transcript_extractor.bound_claims.common import read_json, write_json
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger
from pastor_transcript_extractor.thought_units import candidates as cand, decide, jev, questions, stage

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
