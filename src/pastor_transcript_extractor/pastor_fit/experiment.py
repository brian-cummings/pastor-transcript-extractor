"""Parts 1, 1b and 2 of the pastor fit experiment (spec sections 5 and 6), computed from saved fingerprints.

Ranking with ties is scored by expectation: if `b` candidates are strictly closer than the right
one and `t` others are exactly as close, the right one's expected rank is 1 + b + t/2 and its
chance of being in the top k is clamp((k - b) / (t + 1), 0, 1). Empty fingerprints are infinitely
far from everything, so an empty query ties with every candidate and earns only chance credit.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import statistics
from typing import Iterable, Sequence

import numpy as np

STYLE_WORDS = 300
KINDS = ('style', 'embed')
TOP_K = {'part1': (1, 3), 'part1b': (5,), 'part2': (5,)}
PART1_MIN_SERMONS = (4, 6)
PART1B_MIN_SERMONS = 3
PART2_MIN_PREACHER = 3
PART2_MIN_CHURCH = 3

PASS = {
    'part1_top1': 0.50, 'part1_over_baseline': 0.20, 'part1_same_church_share': 0.80,
    'part1b_top5': 0.80, 'part2_top5_cases': 8, 'part2_median_rank': 5.0,
}


# ---------- fingerprints of groups of sermons ----------

class Fingerprints:
    """Group fingerprints for one text variant: stylometry frequencies and mean embeddings."""

    def __init__(self, counts: dict, chunk_index: dict, cache_vectors: dict):
        self.words = counts['vocabulary'][:STYLE_WORDS]
        self.position = {word: i for i, word in enumerate(self.words)}
        self.style_counts = {}
        self.style_totals = {}
        for video, entry in counts['sermons'].items():
            vector = np.zeros(len(self.words))
            for word, n in entry['counts'].items():
                if word in self.position:
                    vector[self.position[word]] = n
            self.style_counts[int(video)] = vector
            self.style_totals[int(video)] = entry['total']
        self.embed_sums = {}
        self.embed_counts = {}
        self.chunk_index = {int(video): items for video, items in chunk_index.items()}
        for video, items in self.chunk_index.items():
            vectors = [cache_vectors[item['key']] for item in items]
            self.embed_sums[video] = np.sum(vectors, axis=0) if vectors else None
            self.embed_counts[video] = len(vectors)

    def style(self, videos: Iterable[int]):
        videos = list(videos)
        total = sum(self.style_totals[v] for v in videos)
        if total == 0:
            return None
        return sum(self.style_counts[v] for v in videos) / total

    def embed(self, videos: Iterable[int]):
        sums = [self.embed_sums[v] for v in videos if self.embed_sums.get(v) is not None]
        if not sums:
            return None
        mean = np.sum(sums, axis=0)
        norm = float(np.linalg.norm(mean))
        return mean / norm if norm > 0 else None

    def group(self, kind: str, videos: Iterable[int]):
        return self.style(videos) if kind == 'style' else self.embed(videos)


def distances(kind: str, query, candidates: Sequence, reference: Sequence) -> list[float]:
    """Burrows' Delta (z-scored over the reference groups) for style; cosine distance for embed."""
    if query is None:
        return [float('inf')] * len(candidates)
    if kind == 'embed':
        return [float('inf') if c is None else float(1.0 - np.dot(query, c)) for c in candidates]
    present = np.array([r for r in reference if r is not None])
    mean, spread = present.mean(axis=0), present.std(axis=0)
    keep = spread > 0
    zq = (query[keep] - mean[keep]) / spread[keep]
    return [float('inf') if c is None else float(np.mean(np.abs(zq - (c[keep] - mean[keep]) / spread[keep])))
            for c in candidates]


def rank_credit(true_distance: float, other_distances: Iterable[float], ks: Sequence[int]) -> dict:
    others = list(other_distances)
    better = sum(1 for d in others if d < true_distance)
    ties = sum(1 for d in others if d == true_distance)
    credit = {f'top{k}': max(0.0, min(1.0, (k - better) / (ties + 1))) for k in ks}
    credit['expected_rank'] = 1 + better + ties / 2
    credit['candidates'] = len(others) + 1
    return credit


def style_drivers(fp: Fingerprints, query, candidate, reference, limit: int = 10) -> list[str]:
    """Words on which query and candidate deviate from the reference in the same direction, most first."""
    if query is None or candidate is None:
        return []
    present = np.array([r for r in reference if r is not None])
    mean, spread = present.mean(axis=0), present.std(axis=0)
    spread[spread == 0] = np.inf
    product = ((query - mean) / spread) * ((candidate - mean) / spread)
    order = np.argsort(-product)
    return [fp.words[i] for i in order[:limit] if product[i] > 0]


def nearest_chunks(fp: Fingerprints, target, videos: Iterable[int], cache_vectors: dict, limit: int = 3) -> list[str]:
    if target is None:
        return []
    scored = []
    for video in videos:
        for item in fp.chunk_index.get(video, []):
            scored.append((float(np.dot(cache_vectors[item['key']], target)), item['text']))
    scored.sort(key=lambda pair: -pair[0])
    return [' '.join(text.split()[:30]) + ' ...' for _, text in scored[:limit]]


# ---------- population helpers ----------

def by_profile(sermons: list[dict]) -> dict[int, list[dict]]:
    groups: dict[int, list[dict]] = defaultdict(list)
    for sermon in sermons:
        groups[sermon['profile_id']].append(sermon)
    return dict(groups)


def split_halves(sermons: list[dict]) -> tuple[list[int], list[int]]:
    """Fixed split: order by SHA-256 of the YouTube id, then alternate A, B."""
    ordered = sorted(sermons, key=lambda s: hashlib.sha256(s['youtube_video_id'].encode()).hexdigest())
    return [s['video_id'] for s in ordered[0::2]], [s['video_id'] for s in ordered[1::2]]


def same_church_pairs(profiles: dict[int, list[dict]], members: Iterable[int]) -> list[tuple[int, int]]:
    members = sorted(members)
    sources = {p: {s['source_id'] for s in profiles[p]} for p in members}
    return [(p, q) for i, p in enumerate(members) for q in members[i + 1:] if sources[p] & sources[q]]


def part2_cases(profiles: dict[int, list[dict]]) -> list[dict]:
    by_source: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for profile, sermons in profiles.items():
        for sermon in sermons:
            by_source[sermon['source_id']][profile].append(sermon['video_id'])
    cases = []
    for source in sorted(by_source):
        preachers = by_source[source]
        if len(preachers) < 2:
            continue
        for profile in sorted(preachers):
            others = sorted(p for p in preachers if p != profile)
            church = sorted(v for p in others for v in preachers[p])
            if len(preachers[profile]) >= PART2_MIN_PREACHER and len(church) >= PART2_MIN_CHURCH:
                cases.append({'source_id': source, 'profile_id': profile, 'other_preachers': others,
                              'church_sermons': church, 'preacher_sermons_here': len(preachers[profile])})
    return cases


def census(sermons: list[dict]) -> dict:
    profiles = by_profile(sermons)
    groups = {n: sorted(p for p, s in profiles.items() if len(s) >= n) for n in PART1_MIN_SERMONS}
    return {
        'profiles': len(profiles), 'sermons': len(sermons),
        'channels': len({s['source_id'] for s in sermons}),
        'part1_groups': {str(n): {'profiles': len(members),
                                  'same_church_pairs': [list(p) for p in same_church_pairs(profiles, members)]}
                         for n, members in groups.items()},
        'part1b_queries': sum(len(s) for s in profiles.values() if len(s) >= PART1B_MIN_SERMONS),
        'part2_cases': [{k: v for k, v in case.items() if k != 'church_sermons'} | {'church_sermons': len(case['church_sermons'])}
                        for case in part2_cases(profiles)],
    }


# ---------- the parts ----------

def _summary(rows: list[dict], ks: Sequence[int]) -> dict:
    if not rows:
        return {'n': 0, 'median_expected_rank': None, **{f'top{k}': 0.0 for k in ks}}
    out ={f'top{k}': statistics.fmean(r[f'top{k}'] for r in rows) for k in ks}
    out['median_expected_rank'] = statistics.median(r['expected_rank'] for r in rows)
    out['n'] = len(rows)
    return out


def part1(sermons: list[dict], fps: dict[str, Fingerprints], cache_vectors: dict) -> dict:
    profiles = by_profile(sermons)
    result: dict = {}
    for minimum in PART1_MIN_SERMONS:
        members = sorted(p for p, s in profiles.items() if len(s) >= minimum)
        halves = {p: split_halves(profiles[p]) for p in members}
        pairs = same_church_pairs(profiles, members)
        entry: dict = {'profiles': members, 'same_church_pairs': [list(p) for p in pairs], 'results': {}}
        for variant, fp in fps.items():
            for kind in KINDS:
                a = {p: fp.group(kind, halves[p][0]) for p in members}
                b = {p: fp.group(kind, halves[p][1]) for p in members}
                reference = list(a.values()) + list(b.values())
                rows, drivers = [], Counter()
                for p in members:
                    dist = dict(zip(members, distances(kind, a[p], [b[q] for q in members], reference)))
                    credit = rank_credit(dist[p], [dist[q] for q in members if q != p], TOP_K['part1'])
                    row = {'profile_id': p, **credit, 'nearest_other': min((q for q in members if q != p), key=lambda q: dist[q])}
                    if kind == 'style':
                        row['shared_words'] = style_drivers(fp, a[p], b[p], reference)
                        if credit['top1'] == 1.0:
                            drivers.update(row['shared_words'])
                    elif minimum == PART1_MIN_SERMONS[0] and variant == 'clean':
                        row['nearest_chunks_of_other_half'] = nearest_chunks(fp, a[p], halves[p][1], cache_vectors, 2)
                    rows.append(row)
                church = []
                for p, q in pairs:
                    for x, y in ((p, q), (q, p)):
                        own, rival = distances(kind, a[x], [b[x], b[y]], reference)
                        church.append({'query': x, 'rival': y, 'win': 1.0 if own < rival else 0.5 if own == rival else 0.0})
                entry['results'][f'{kind}/{variant}'] = {
                    'summary': _summary(rows, TOP_K['part1']),
                    'same_church': {'wins': sum(c['win'] for c in church), 'comparisons': len(church), 'rows': church},
                    'rows': rows,
                    'words_most_often_driving_correct_matches': [w for w, _ in drivers.most_common(25)]}
        result[str(minimum)] = entry
    return result


def part1b(sermons: list[dict], fps: dict[str, Fingerprints]) -> dict:
    profiles = by_profile(sermons)
    ids = sorted(profiles)
    result = {}
    for variant, fp in fps.items():
        for kind in KINDS:
            full = {p: fp.group(kind, [s['video_id'] for s in profiles[p]]) for p in ids}
            rows = []
            for p in ids:
                if len(profiles[p]) < PART1B_MIN_SERMONS:
                    continue
                for sermon in profiles[p]:
                    held = sermon['video_id']
                    candidates = dict(full)
                    candidates[p] = fp.group(kind, [s['video_id'] for s in profiles[p] if s['video_id'] != held])
                    query = fp.group(kind, [held])
                    reference = list(candidates.values())
                    dist = dict(zip(ids, distances(kind, query, [candidates[q] for q in ids], reference)))
                    rows.append({'video_id': held, 'profile_id': p,
                                 **rank_credit(dist[p], [dist[q] for q in ids if q != p], TOP_K['part1b'])})
            result[f'{kind}/{variant}'] = {'summary': _summary(rows, TOP_K['part1b']), 'rows': rows}
    return result


def part2(sermons: list[dict], fps: dict[str, Fingerprints], cache_vectors: dict) -> dict:
    profiles = by_profile(sermons)
    ids = sorted(profiles)
    cases = part2_cases(profiles)
    result = {'cases': [{k: v for k, v in c.items() if k != 'church_sermons'} for c in cases], 'results': {}}
    for variant, fp in fps.items():
        for kind in KINDS:
            full = {p: fp.group(kind, [s['video_id'] for s in profiles[p]]) for p in ids}
            rows = []
            for case in cases:
                church = fp.group(kind, case['church_sermons'])
                pool = [q for q in ids if q not in case['other_preachers']]
                reference = [full[q] for q in pool] + [church]
                dist = dict(zip(pool, distances(kind, church, [full[q] for q in pool], reference)))
                p = case['profile_id']
                ranked = sorted(pool, key=lambda q: dist[q])
                row = {'source_id': case['source_id'], 'profile_id': p,
                       **rank_credit(dist[p], [dist[q] for q in pool if q != p], TOP_K['part2']),
                       'top_candidates': ranked[:5]}
                if kind == 'style':
                    row['shared_words'] = style_drivers(fp, church, full[p], reference)
                else:
                    row['preacher_chunks_nearest_church'] = nearest_chunks(
                        fp, church, [s['video_id'] for s in profiles[p]], cache_vectors)
                rows.append(row)
            summary = _summary(rows, TOP_K['part2']) if rows else {'n': 0}
            if rows:
                summary['top5_cases'] = sum(r['top5'] for r in rows)
            result['results'][f'{kind}/{variant}'] = {'summary': summary, 'rows': rows}
    return result


def verdicts(p1: dict, p1b: dict, p2: dict) -> dict:
    """Apply the pass marks of spec section 6, per fingerprint kind."""
    out = {}
    main = p1[str(PART1_MIN_SERMONS[0])]['results']
    for kind in KINDS:
        clean, base = main[f'{kind}/clean'], main[f'{kind}/baseline']
        church = clean['same_church']
        share = church['wins'] / church['comparisons'] if church['comparisons'] else 0.0
        part1_pass = (clean['summary']['top1'] >= PASS['part1_top1']
                      and clean['summary']['top1'] - base['summary']['top1'] >= PASS['part1_over_baseline'])
        s2 = p2['results'][f'{kind}/stripped']['summary']
        out[kind] = {
            'part1_overall': part1_pass,
            'part1_same_church': share >= PASS['part1_same_church_share'],
            'part1b': p1b[f'{kind}/clean']['summary']['top5'] >= PASS['part1b_top5'],
            'part2': bool(s2.get('n')) and s2['top5_cases'] >= PASS['part2_top5_cases']
                     and s2['median_expected_rank'] <= PASS['part2_median_rank'],
        }
    return out
