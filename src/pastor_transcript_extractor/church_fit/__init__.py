"""Church fit reading (concerns framework, docs/BENCHMARK_EXPLAINER.md section 1): rank pastors on a church's stated
want concerns and surface avoid-concern passages for review. Free: it reads the Jev answers and free measures the
benchmark explainer already saved. Never applies labels; an avoid concern produces passages to read, not a verdict.

Rules (fixed 2026-11-24, before any result):
- Measure value per pastor: share of preaching blocks at or above the floor (topics 0.55, other leaves 0.8); free
  measures are the mean over sermons (the explainer's `values`). Robust z against the pool pastors, clipped to +-3 so a
  rare leaf cannot dominate.
- Want concern score: mean of its "for" z values and negated "against" z values.
- Breadth: the share of his sermons on the want side (the mean sign of value minus pool median, against flipped) > 0.
- Want fit: importance-weighted mean of want concern scores (high 2, medium 1).
- Avoid concern: matching blocks, the number of sermons they occur in, and passages. A pastor is listed for review
  when matches occur in at least 2 sermons. Nothing is netted against the want fit.
- Pastors with fewer than 3 sermons are left out of the ranking.
"""
from __future__ import annotations

import statistics
from pathlib import Path
from typing import Mapping, Sequence

from ..benchmark_explainer import free, values

Z_CLIP = 3.0
MIN_SERMONS = 3
AVOID_REVIEW_SERMONS = 2


def _clip(value: float | None) -> float | None:
    return None if value is None else max(-Z_CLIP, min(Z_CLIP, value))


def _sermon_value(name: str, video: int, scored: Mapping[int, Mapping], measured: Mapping[int, Mapping]) -> float | None:
    if name in free.DIMENSIONS:
        return measured.get(video, {}).get(name)
    blocks = scored.get(video, {}).get('blocks', [])
    if not blocks:
        return None
    return sum(1 for b in blocks if b['signals'].get(name, 0.0) >= values.floor_for(name)) / len(blocks)


def want_score(concern: Mapping, table_row: Mapping, scales: Mapping) -> dict:
    parts = {}
    for name in concern['for']:
        parts[name] = _clip(values.z(table_row.get(name, {}).get('value'), name, scales))
    for name in concern.get('against', []):
        z = _clip(values.z(table_row.get(name, {}).get('value'), name, scales))
        parts[name] = None if z is None else -z
    present = [v for v in parts.values() if v is not None]
    return dict(score=statistics.fmean(present) if present else None, parts=parts)


def breadth(concern: Mapping, videos: Sequence[int], scored, measured, scales) -> dict:
    on_side = judged = 0
    for video in videos:
        signs = []
        for name, sign in [(n, 1) for n in concern['for']] + [(n, -1) for n in concern.get('against', [])]:
            value = _sermon_value(name, video, scored, measured)
            if value is None or name not in scales:
                continue
            delta = value - scales[name][0]
            signs.append(sign * (1 if delta > 0 else -1 if delta < 0 else 0))
        if signs:
            judged += 1
            on_side += statistics.fmean(signs) > 0
    return dict(sermons=judged, on_want_side=on_side, share=on_side / judged if judged else None)


def avoid_matches(concern: Mapping, videos: Sequence[int], scored: Mapping[int, Mapping]) -> dict:
    matches = []
    for video in videos:
        for block in scored.get(video, {}).get('blocks', []):
            hit = {n: block['signals'][n] for n in concern['for'] if block['signals'].get(n, 0.0) >= values.floor_for(n)}
            if hit:
                matches.append(dict(video_id=video, start_seconds=block['start_seconds'], measures=hit,
                                    text=' '.join(block['text'].split())[:700]))
    sermons = sorted({m['video_id'] for m in matches})
    matches.sort(key=lambda m: -max(m['measures'].values()))
    return dict(blocks=len(matches), sermons=len(sermons), review=len(sermons) >= AVOID_REVIEW_SERMONS, passages=matches[:6])


def reading(concerns: Mapping, sermons: Sequence[Mapping], scored, measured, table) -> dict:
    by_pastor: dict[str, list[int]] = {}
    for sermon in sermons:
        by_pastor.setdefault(sermon['pastor'], []).append(sermon['video_id'])
    pool = sorted(p for p in by_pastor if p.startswith('p'))
    scales = values.reference_scales(table, pool)
    weights = concerns['importance_weights']
    pastors = {}
    for pastor, videos in by_pastor.items():
        if len(videos) < MIN_SERMONS:
            continue
        row = dict(sermons=len(videos), wants={}, avoids={})
        weighted = []
        for concern in concerns['concerns']:
            if concern['kind'] == 'want':
                score = want_score(concern, table[pastor], scales)
                score['breadth'] = breadth(concern, videos, scored, measured, scales)
                score['evidence'] = [e for name in concern['for'] if name not in free.DIMENSIONS
                                     for e in values.evidence(name, videos, scored, measured, limit=1)][:2]
                row['wants'][concern['id']] = score
                if score['score'] is not None:
                    weighted.append((weights[concern['importance']], score['score']))
            elif concern['for']:
                row['avoids'][concern['id']] = avoid_matches(concern, videos, scored)
        total = sum(w for w, _ in weighted)
        row['want_fit'] = sum(w * s for w, s in weighted) / total if total else None
        pastors[pastor] = row
    order = sorted((p for p in pastors if pastors[p]['want_fit'] is not None), key=lambda p: -pastors[p]['want_fit'])
    for rank, pastor in enumerate(order, 1):
        pastors[pastor]['rank'] = rank
    return dict(version=concerns['version'], rules=__doc__.split('Rules', 1)[1].strip(), ranked=order, pastors=pastors)
