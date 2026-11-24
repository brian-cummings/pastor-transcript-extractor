from collections import Counter
import math

from pathlib import Path
import tempfile
import unittest

import numpy as np

from pastor_transcript_extractor.pastor_fit import cleaning, experiment, fingerprints
from pastor_transcript_extractor.pastor_fit.runner import _once

WELCOME = 'Welcome to Grace Chapel we are so glad you joined us this morning online'


def _fake_encoder(text):
    words = text.split()
    vector = np.zeros(384)
    for word in words:
        vector[hash(word) % 384] += 1.0
    return list(vector / np.linalg.norm(vector))


def _corpus():
    """Two distinctive pastors per channel; pastor vocabulary is shared within a pastor."""
    styles = {1: 'grace mercy covenant', 2: 'battle victory armor', 3: 'river garden harvest', 4: 'light lamp window'}
    sermons, texts = [], {}
    video = 0
    for profile, words in styles.items():
        for n in range(4):
            video += 1
            sermons.append({'video_id': video, 'profile_id': profile, 'source_id': 1 if profile < 3 else 2,
                            'youtube_video_id': f'y{video}'})
            texts[video] = ' '.join([f'{words} sermon {n} and the word of the lord'] * 20)
    return sermons, texts


class PastorFitTests(unittest.TestCase):
    def test_boilerplate_removed_only_when_shared_across_a_channels_sermons(self):
        texts = {1: f'{WELCOME}. Love your neighbor.', 2: f'{WELCOME}. Faith comes by hearing.',
                 3: f'{WELCOME}. Hope does not disappoint.', 4: f'{WELCOME}. Another church entirely.'}
        channel_of = {1: 10, 2: 10, 3: 10, 4: 20}
        variants, record = cleaning.variants(texts, channel_of)
        assert 'Welcome' not in variants['clean'][1] and 'Love your neighbor.' in variants['clean'][1]
        assert 'Welcome' in variants['baseline'][1]
        # channel 20 has one sermon, below the three-sermon floor
        assert 'Welcome' in variants['clean'][4]
        assert record['sermons']['1']['boilerplate_units'] == 1

    def test_boilerplate_marks_short_units_inside_a_repeated_passage(self):
        grams = cleaning.shingles(cleaning.tokens('let us pray together now father we thank you'))
        kept, removed = cleaning.split_boilerplate('Let us pray. Together now father we thank you. Grace is free.', grams)
        assert kept == ['Grace is free.'] and len(removed) == 2

    def test_channel_vocabulary_needs_half_inside_and_rare_outside(self):
        token_sets = {1: {'bethany', 'grace'}, 2: {'bethany', 'grace'}, 3: {'grace'},
                      **{i: {'grace'} for i in range(4, 40)}}
        channel_of = {1: 1, 2: 1, 3: 1, **{i: 2 for i in range(4, 40)}}
        vocabulary = cleaning.channel_vocabulary(token_sets, channel_of)
        assert vocabulary[1] == {'bethany'}
        text, removed = cleaning.remove_words('Bethany, grace and peace', vocabulary[1])
        assert text == 'grace and peace' and removed == ['Bethany,']

    def test_rank_credit_shares_ties_and_counts_better_candidates(self):
        assert experiment.rank_credit(1.0, [2.0, 3.0], (1,)) == {'top1': 1.0, 'expected_rank': 1.0, 'candidates': 3}
        tied = experiment.rank_credit(1.0, [1.0, 0.5], (1, 3))
        assert tied['top1'] == 0.0 and tied['top3'] == 1.0 and tied['expected_rank'] == 2.5
        empty = experiment.rank_credit(math.inf, [math.inf] * 3, (1,))
        assert empty['top1'] == 0.25

    def test_split_is_fixed_and_alternating(self):
        sermons = [{'video_id': i, 'youtube_video_id': f'yt{i}'} for i in range(5)]
        a, b = experiment.split_halves(sermons)
        assert (a, b) == experiment.split_halves(list(reversed(sermons)))
        assert len(a) == 3 and len(b) == 2 and not set(a) & set(b)

    def test_part2_cases_exclude_thin_preachers_and_thin_churches(self):
        def sermon(v, p, s):
            return {'video_id': v, 'profile_id': p, 'source_id': s, 'youtube_video_id': str(v)}
        sermons = ([sermon(i, 1, 9) for i in range(3)] + [sermon(i, 2, 9) for i in range(3, 5)]
                   + [sermon(i, 3, 8) for i in range(5, 9)])
        cases = experiment.part2_cases(experiment.by_profile(sermons))
        # preacher 1 has 3 sermons but the church's other preacher has only 2; preacher 2 has only 2
        assert cases == []
        sermons.append(sermon(9, 2, 9))
        cases = experiment.part2_cases(experiment.by_profile(sermons))
        assert [(c['profile_id'], c['other_preachers']) for c in cases] == [(1, [2]), (2, [1])]

    def test_parts_recover_distinct_pastors_end_to_end(self):
        tmp_path = Path(tempfile.mkdtemp())
        sermons, texts = _corpus()
        cache = fingerprints.EmbeddingCache(tmp_path / 'cache.npz')
        fps = {}
        for variant in ('clean', 'stripped', 'baseline'):
            chunk_index, _ = fingerprints.build_embeddings(texts, _fake_encoder, cache)
            fps[variant] = experiment.Fingerprints(fingerprints.word_counts(texts), chunk_index, cache.vectors)
        p1 = experiment.part1(sermons, fps, cache.vectors)
        for kind in experiment.KINDS:
            assert p1['4']['results'][f'{kind}/clean']['summary']['top1'] == 1.0
            assert p1['4']['results'][f'{kind}/clean']['same_church']['comparisons'] == 4
        p1b = experiment.part1b(sermons, fps)
        assert p1b['embed/clean']['summary']['top5'] == 1.0
        p2 = experiment.part2(sermons, fps, cache.vectors)
        assert len(p2['cases']) == 4
        verdicts = experiment.verdicts(p1, p1b, p2)
        assert set(verdicts) == set(experiment.KINDS)

    def test_embedding_halves_chunks_the_model_cannot_take(self):
        tmp_path = Path(tempfile.mkdtemp())
        cache = fingerprints.EmbeddingCache(tmp_path / 'cache.npz')
        stats = Counter()
        long_text = ' '.join(['word'] * 150)
        calls = []

        def picky(text):
            calls.append(len(text.split()))
            return None if len(text.split()) > 80 else [1.0] + [0.0] * 383
        pieces = fingerprints.embed_chunks(long_text, picky, cache, stats)
        assert [len(p.split()) for p, _ in pieces] == [75, 75] and stats['split_chunks'] == 1
        cache.save()
        assert len(fingerprints.EmbeddingCache(tmp_path / 'cache.npz').vectors) == 1

    def test_steps_run_once(self):
        done = Path(tempfile.mkdtemp()) / 'part1.json'
        done.write_text('{}')
        try:
            _once(done)
        except ValueError as error:
            assert 'runs once' in str(error)
        else:
            raise AssertionError('expected a refusal')



if __name__ == '__main__':
    unittest.main()
