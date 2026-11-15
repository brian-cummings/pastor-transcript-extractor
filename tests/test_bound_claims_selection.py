from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.bound_claims import leaf_pass, slice as slicing, strata
from pastor_transcript_extractor.bound_claims.common import file_sha256, read_json, write_json
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger
from pastor_transcript_extractor.sermon_classifier_typesafe import (
    SALVATION_RELATIONSHIPS_PACK, TOPIC_PACK, TREATMENT_PACK, TypeSafeBlockAnswer)
from pastor_transcript_extractor.sermon_leaf_packs import LEAF_PACKS
from pastor_transcript_extractor.sermon_salvation_relationships import SALVATION_RELATIONSHIPS
from pastor_transcript_extractor.sermon_semantic_dimensions import SEMANTIC_DIMENSIONS
from pastor_transcript_extractor.sermon_topics import TOPICS


def levels(mass):
    """Level distribution whose Supporting-or-above mass is `mass`."""
    return {'0': round(1 - mass, 6), '1': 0.0, '2': mass, '3': 0.0, '4': 0.0}


def write_sermon(root: Path, name: str, masses):
    """Cached topic projection with one block per (salvation, public) mass pair."""
    folder = root / name / 'extracted'
    folder.mkdir(parents=True)
    blocks = []
    for index, (salvation, public) in enumerate(masses):
        scores = {topic: dict(score=0.0, confidence=0.9, probabilities=levels(0.0)) for topic in TOPICS}
        scores['salvation_gospel']['probabilities'] = levels(salvation)
        scores['society_public_life']['probabilities'] = levels(public)
        blocks.append(dict(block_id=index, start_seconds=index * 20.0, end_seconds=index * 20.0 + 19.0, segment_indexes=[index],
                           context=dict(leading_context='', target_text=f'{name} block {index} text.', trailing_context='', diagnostics={}),
                           scores=scores))
    path = folder / 'proposed.json'
    path.write_text(json.dumps(dict(classification=dict(model='jev-1.13.0', search=dict(topic_analysis=dict(blocks=blocks))))))
    return path


def row(profile, video, path, attached=5, label=None):
    return dict(profile_id=profile, display_label=label, lifecycle_state='active', video_id=video, youtube_video_id=f'yt{video}',
                title=f'Sermon {video}', url=f'https://youtu.be/{video}', published_at=None, duration_seconds=1800,
                source_path=str(path), attached_sermons=attached)


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def assess_blocks(self, recording_context, blocks, *, requested_packs=None, topic_contexts=None, **kwargs):
        packs = set(requested_packs)
        self.calls.append((sorted(packs), [block.block_id for block in blocks]))
        answers = {}
        for block in blocks:
            context = {**topic_contexts[block.block_id].state_payload(), 'diagnostics': dict(topic_contexts[block.block_id].diagnostics)}
            fields = dict(choice='unclear', probabilities={}, confidence=None, resolved_model_id='jev-1.13.0',
                          request_provenance=dict(input_tokens=1000, output_tokens=0, request_key='k'))
            if TOPIC_PACK in packs:
                fields.update(topic_scores={topic: dict(score=1.0, confidence=0.9, probabilities=levels(0.5)) for topic in TOPICS},
                              topic_question_version='v', topic_context=context)
            if SALVATION_RELATIONSHIPS_PACK in packs:
                from pastor_transcript_extractor.sermon_salvation_relationships import SALVATION_RELATIONSHIPS_PACK_VERSION
                fields.update(salvation_relationship_probabilities={n: 0.1 for n in SALVATION_RELATIONSHIPS},
                              salvation_relationship_question_version=SALVATION_RELATIONSHIPS_PACK_VERSION,
                              salvation_relationship_context=context)
            if TREATMENT_PACK in packs:
                fields.update(semantic_probabilities={n: 0.2 for n in SEMANTIC_DIMENSIONS}, semantic_question_version='v')
            fields['leaf_answers'] = {pack: dict(version=pack, probabilities={leaf: 0.3 for leaf in LEAF_PACKS[pack].definitions}, context=context)
                                      for pack in packs if pack in LEAF_PACKS}
            answers[block.block_id] = TypeSafeBlockAnswer(**fields)
        return answers


class SliceTests(unittest.TestCase):
    def test_relaxes_floor_when_too_few_profiles_and_records_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows, attention = [], {}
            for profile, videos, public in ((318, (1, 2, 3), 9), (10, (4, 5, 6), 1), (11, (7, 8, 9), 5), (12, (10, 11, 12), 0),
                                           (13, (13, 14), 0), (14, (15, 16), 0)):
                for video in videos:
                    path = write_sermon(root, f'v{video}', [(0.5, 0.5)])
                    rows.append(row(profile, video, path, attached=len(videos) + (3 if profile == 13 else 0)))
                    attention[str(path)] = dict(block_count=1, model='jev-1.13.0', public_life_near_or_above=public, public_life_strong=public)
            result = slicing.build_slice(rows, lambda source: attention[source])
            self.assertEqual([318, 11, 10, 12, 13], [p['profile_id'] for p in result['profiles']])
            self.assertEqual(10, len(result['sermons']))
            self.assertEqual(1, len([n for n in result['notes'] if 'floor was relaxed' in n]))
            first_pair = [s['video_id'] for s in result['sermons'] if s['profile_id'] == 318]
            self.assertEqual([1, 3], first_pair)  # earliest/latest by video id when undated

    def test_fewer_than_five_available_profiles_is_recorded_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = []
            for profile in (318, 10, 11, 12):
                for video in range(profile * 10, profile * 10 + 3):
                    rows.append(row(profile, video, write_sermon(root, f'v{video}', [(0.5, 0.5)])))
            result = slicing.build_slice(rows, lambda source: dict(block_count=1, model='m', public_life_near_or_above=0, public_life_strong=0))
            self.assertEqual(4, len(result['profiles']))
            self.assertEqual(8, len(result['sermons']))
            self.assertTrue(any('fewer profiles than requested' in n for n in result['notes']))

    def test_too_few_profiles_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_sermon(Path(directory), 'a', [(0.5, 0.5)])
            with self.assertRaises(ValueError):
                slicing.build_slice([row(1, 1, path), row(1, 2, path)], lambda source: dict(block_count=1, model='m', public_life_near_or_above=0, public_life_strong=0))

    def test_approval_requires_the_exact_file_hash_and_unchanged_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_sermon(root, 'a', [(0.5, 0.5)])
            path = root / 'slice.json'
            write_json(path, dict(version=slicing.VERSION, sermons=[dict(video_id=1, source_path=str(source), source_sha256=file_sha256(source))]))
            approved = file_sha256(path)
            self.assertEqual(slicing.VERSION, slicing.verify_slice(path, approved)['version'])
            with self.assertRaises(ValueError):
                slicing.verify_slice(path, '0' * 64)
            source.write_text('{}')
            with self.assertRaises(ValueError):
                slicing.verify_slice(path, approved)


class LeafPassTests(unittest.TestCase):
    def make(self, root):
        source = write_sermon(root, 'a', [(0.8, 0.0), (0.5, 0.0), (0.0, 0.8)])
        slice_path = root / 'pilot' / 'slice.json'
        write_json(slice_path, dict(version=slicing.VERSION, sermons=[dict(
            profile_id=1, video_id=7, youtube_video_id='yt7', title='T', url='https://youtu.be/7', source_path=str(source),
            source_sha256=file_sha256(source), cache_dir=str(source.parent / 'inference-cache'), model='jev-1.13.0', block_count=3)]))
        return slice_path, file_sha256(slice_path), PilotLedger(root / 'pilot' / 'ledger.json')

    def test_check_only_counts_misses_without_a_client_or_ledger_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            slice_path, approved, ledger = self.make(Path(directory))
            plan = leaf_pass.run(slice_path, approved, ledger, check_only=True, letters='TSPLMH',
                                 client_factory=lambda model: self.fail('check-only must not open a client'))
            self.assertEqual({letter: 3 for letter in 'TSPLMH'}, plan['cache_misses'])
            self.assertEqual(0, ledger.attempt_count())
            # topic: 3 blocks/request (75//20), salvation 6, others 6 -> one request each per sermon of 3 blocks
            self.assertEqual(6, plan['worst_case_requests'])

    def test_collects_all_59_signals_reserves_each_request_and_reuses_the_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            slice_path, approved, ledger = self.make(Path(directory))
            adapter = FakeAdapter()
            result = leaf_pass.run(slice_path, approved, ledger, letters='TSPLMH', client_factory=lambda model: adapter)
            self.assertEqual(6, result['physical_requests'])
            table = read_json(Path(result['output']))
            block = table['sermons'][0]['blocks'][0]
            self.assertEqual(59, len(block['signals']))
            self.assertEqual({'T': 20, 'S': 12, 'P': 8, 'L': 9, 'M': 6, 'H': 4}, {letter: sum(k.startswith(letter + ':') for k in block['signals']) for letter in 'TSPLMH'})
            self.assertAlmostEqual(0.5, block['signals']['T:salvation_gospel'])  # the fake adapter's topic mass
            self.assertEqual('v7b0', block['coordinate'])
            summary = ledger.summary()['steps']['leaf']
            self.assertEqual((6, 0, '0.000252000'), (summary['attempts'], summary['unresolved'], summary['known_usd']))
            again = leaf_pass.run(slice_path, approved, ledger, letters='TSPLMH', client_factory=lambda model: self.fail('cache hit opened a client'))
            self.assertEqual((0, 0), (again['physical_requests'], sum(again['cache_misses'].values())))

    def test_refuses_when_worst_case_attempts_leave_no_room_for_later_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            slice_path, approved, _ = self.make(Path(directory))
            tight = PilotLedger(Path(directory) / 'pilot' / 'ledger.json', ceiling_usd=Decimal('5.00'), ceiling_attempts=450)
            with self.assertRaises(ValueError):
                leaf_pass.run(slice_path, approved, tight, letters='TSPLMH', client_factory=lambda model: FakeAdapter())

    def test_missing_usage_keeps_the_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            slice_path, approved, ledger = self.make(Path(directory))

            class Silent(FakeAdapter):
                def assess_blocks(self, *args, **kwargs):
                    answers = super().assess_blocks(*args, **kwargs)
                    for answer in answers.values():
                        answer.request_provenance['input_tokens'] = None
                    return answers
            leaf_pass.run(slice_path, approved, ledger, letters='T', client_factory=lambda model: Silent())
            self.assertEqual(1, ledger.summary()['steps']['leaf']['unresolved'])

    def test_default_packs_skip_the_opt_in_leaf_packs(self):
        with tempfile.TemporaryDirectory() as directory:
            slice_path, approved, ledger = self.make(Path(directory))
            plan = leaf_pass.run(slice_path, approved, ledger, check_only=True)
            self.assertEqual('TSPH', plan['packs'])

    def test_packs_option_limits_the_run(self):
        with tempfile.TemporaryDirectory() as directory:
            slice_path, approved, ledger = self.make(Path(directory))
            plan = leaf_pass.run(slice_path, approved, ledger, check_only=True, letters='TSP')
            self.assertEqual('TSP', plan['packs'])
            self.assertEqual(3, plan['worst_case_requests'])


class StrataTests(unittest.TestCase):
    def leaf(self, masses, slice_sha='s'):
        blocks = []
        for ordinal, (salvation, public) in enumerate(masses):
            signals = {f'T:{topic}': 0.0 for topic in TOPICS}
            signals['T:salvation_gospel'], signals['T:society_public_life'] = salvation, public
            signals.update({f'S:{n}': 0.0 for n in SALVATION_RELATIONSHIPS})
            blocks.append(dict(coordinate=f'v1b{ordinal}', block_id=ordinal, ordinal=ordinal, start_seconds=ordinal * 20.0,
                               end_seconds=ordinal * 20.0 + 19.0, text=f'text {ordinal}', signals=signals))
        return dict(slice_sha256=slice_sha, sermons=[dict(video_id=1, profile_id=1, title='T', url='https://youtu.be/1', blocks=blocks)])

    def test_selection_is_deterministic_disjoint_and_reports_shortfalls(self):
        masses = [(0.9, 0.0)] * 30 + [(0.5, 0.0)] * 10 + [(0.0, 0.8)] * 4 + [(0.9, 0.9)] * 2 + [(0.0, 0.0)] * 20
        first = strata.select(self.leaf(masses), 'seed')
        second = strata.select(self.leaf(masses), 'seed')
        self.assertEqual(first, second)
        self.assertNotEqual(first['blocks'], strata.select(self.leaf(masses), 'other')['blocks'])
        by = {row['stratum']: row for row in first['report']}
        self.assertEqual((6, 14), (by['public_life_strong']['selected'], by['public_life_strong']['shortfall']))
        self.assertEqual((25, 0), (by['salvation_strong']['selected'], by['salvation_strong']['shortfall']))
        self.assertEqual((10, 10), (by['salvation_near']['selected'], by['salvation_near']['shortfall']))
        self.assertEqual((15, 0), (by['absent_control']['selected'], by['absent_control']['shortfall']))
        coordinates = [block['coordinate'] for block in first['blocks']]
        self.assertEqual(len(coordinates), len(set(coordinates)))
        # A block high on both topics goes to the scarcer public-life stratum first.
        both = [b for b in first['blocks'] if b['signals']['T:salvation_gospel'] == 0.9 and b['signals']['T:society_public_life'] == 0.9]
        self.assertTrue(all(b['stratum'] == 'public_life_strong' for b in both))

    def test_context_blocks_are_full_neighbours_and_gaps_are_empty(self):
        leaf = self.leaf([(0.9, 0.0)] * 3)
        leaf['sermons'][0]['blocks'][2]['start_seconds'] = 500.0
        chosen = {b['coordinate']: b for b in strata.select(leaf, 'x')['blocks']}
        self.assertEqual(('', 'text 1'), (chosen['v1b0']['preceding_text'], chosen['v1b0']['following_text']))
        self.assertEqual(('text 0', ''), (chosen['v1b1']['preceding_text'], chosen['v1b1']['following_text']))
        self.assertEqual('', chosen['v1b2']['preceding_text'])

    def test_requires_topic_signals_and_matching_slice(self):
        leaf = self.leaf([(0.9, 0.0)])
        del leaf['sermons'][0]['blocks'][0]['signals']['T:society_public_life']
        with self.assertRaises(ValueError):
            strata.select(leaf, 'x')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / 'slice.json', {'a': 1})
            write_json(root / 'leaf.json', self.leaf([(0.9, 0.0)], slice_sha='different'))
            with self.assertRaises(ValueError):
                strata.run(root / 'slice.json', root / 'leaf.json', root / 'strata.json')

    def test_absent_control_needs_leaf_signals_to_be_low(self):
        leaf = self.leaf([(0.0, 0.0)] * 3)
        leaf['sermons'][0]['blocks'][0]['signals']['S:atonement_as_basis'] = 0.5
        chosen = {b['coordinate'] for b in strata.select(leaf, 'x')['blocks']}
        self.assertEqual({'v1b1', 'v1b2'}, chosen)


if __name__ == '__main__':
    unittest.main()
