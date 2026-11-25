"""Pastor values, distinctiveness, stability, evidence and ranking (spec sections 4 and 5, steps 4 to 8).

A Jev dimension's value is the share of a pastor's blocks at or above the floor (topics 0.55, every other
leaf 0.8), never a probability. S and P blocks off the route count as below the floor. A free dimension's
value is the mean over the pastor's sermons. A robust z uses the median and 1.4826 x MAD of the reference
pastors; when the MAD is 0 it falls back to 1.2533 x the mean absolute deviation from the median (fixed in
section 10 before any result), and the dimension is "not enough evidence" if that is 0 too.
"""
from __future__ import annotations

from collections import defaultdict
import statistics
from typing import Iterable, Mapping, Sequence

from ..pastor_fit.experiment import split_halves
from . import free

TOPIC_FLOOR = 0.55
LEAF_FLOOR = 0.8
DISTINCT_Z = 1.5
STABLE_Z = 1.0
MIN_BLOCKS = 30
MAX_EXPLAINED = 10
EVIDENCE_PER_DIMENSION = 2
SHORTLIST = 5


def floor_for(signal: str) -> float:
    return TOPIC_FLOOR if signal.startswith('T:') else LEAF_FLOOR


def jev_dimensions(scored: Iterable[Mapping]) -> list[str]:
    names = set()
    for sermon in scored:
        for block in sermon['blocks']:
            names.update(block['signals'])
    return sorted(names)


def pastor_values(scored: Mapping[int, Mapping], measured: Mapping[int, Mapping], sermons: Sequence[Mapping],
                  dimensions: Sequence[str]) -> dict[str, dict[str, dict]]:
    """values[pastor][dimension] = {'value', 'n'} where n is blocks (Jev) or sermons (free)."""
    by_pastor: dict[str, list[int]] = defaultdict(list)
    for sermon in sermons:
        by_pastor[sermon['pastor']].append(sermon['video_id'])
    return {pastor: group_values(videos, scored, measured, dimensions) for pastor, videos in by_pastor.items()}


def group_values(videos: Sequence[int], scored: Mapping[int, Mapping], measured: Mapping[int, Mapping],
                 dimensions: Sequence[str]) -> dict[str, dict]:
    out = {}
    blocks = [b for v in videos if v in scored for b in scored[v]['blocks']]
    for name in dimensions:
        hits = sum(1 for b in blocks if b['signals'].get(name, 0.0) >= floor_for(name))
        out[name] = {'value': hits / len(blocks) if blocks else None, 'n': len(blocks)}
    for name in free.DIMENSIONS:
        values = [measured[v][name] for v in videos if v in measured and measured[v].get(name) is not None]
        out[name] = {'value': statistics.fmean(values) if values else None, 'n': len(values)}
    return out


def scale(values: Sequence[float]) -> tuple[float, float]:
    median = statistics.median(values)
    deviations = [abs(v - median) for v in values]
    mad = 1.4826 * statistics.median(deviations)
    if mad == 0:
        mad = 1.2533 * statistics.fmean(deviations)
    return median, mad


def reference_scales(values: Mapping[str, Mapping[str, dict]], reference: Sequence[str]) -> dict[str, tuple[float, float]]:
    scales = {}
    names = next(iter(values.values())).keys()
    for name in names:
        present = [values[p][name]['value'] for p in reference if values[p][name]['value'] is not None]
        if len(present) >= 5:
            scales[name] = scale(present)
    return scales


def z(value: float | None, name: str, scales: Mapping[str, tuple[float, float]]) -> float | None:
    if value is None or name not in scales or scales[name][1] == 0:
        return None
    median, spread = scales[name]
    return (value - median) / spread


def explain(benchmark: str, sermons: Sequence[Mapping], values: Mapping[str, Mapping[str, dict]],
            scored: Mapping[int, Mapping], measured: Mapping[int, Mapping], dimensions: Sequence[str]) -> dict:
    """Distinctive and stable dimensions of one benchmark against every other pastor."""
    reference = [p for p in values if p != benchmark]
    scales = reference_scales(values, reference)
    own = [s for s in sermons if s['pastor'] == benchmark]
    half_a, half_b = split_halves(own)
    halves = [group_values(half, scored, measured, dimensions) for half in (half_a, half_b)]
    rows, not_enough = [], []
    for name, entry in values[benchmark].items():
        z_all = z(entry['value'], name, scales)
        if z_all is None or (name[0] != 'F' and entry['n'] < MIN_BLOCKS):
            not_enough.append(name)
            continue
        z_halves = [z(h[name]['value'], name, scales) for h in halves]
        distinct = abs(z_all) >= DISTINCT_Z
        stable = all(v is not None and abs(v) >= STABLE_Z and (v > 0) == (z_all > 0) for v in z_halves)
        rows.append(dict(dimension=name, value=entry['value'], n=entry['n'], pool_median=scales[name][0],
                         z=z_all, z_halves=z_halves, distinct=distinct, stable=stable))
    chosen = sorted((r for r in rows if r['distinct'] and r['stable']), key=lambda r: -abs(r['z']))[:MAX_EXPLAINED]
    for row in chosen:
        row['evidence'] = evidence(row['dimension'], [s['video_id'] for s in own], scored, measured, high=row['z'] > 0)
    return dict(benchmark=benchmark, sermons=len(own), halves=[len(half_a), len(half_b)], explained=chosen,
                distinct_but_unstable=[r['dimension'] for r in rows if r['distinct'] and not r['stable']],
                not_enough_evidence=not_enough, all_rows=rows)


def evidence(name: str, videos: Sequence[int], scored: Mapping[int, Mapping], measured: Mapping[int, Mapping],
             *, high: bool = True, limit: int = EVIDENCE_PER_DIMENSION) -> list[dict]:
    if name.startswith('F:'):
        per = sorted(((measured[v][name], v) for v in videos if v in measured and measured[v].get(name) is not None),
                     reverse=high)
        return [dict(video_id=v, sermon_value=value) for value, v in per[:limit]]
    candidates = []
    for v in videos:
        for block in scored.get(v, {}).get('blocks', []):
            p = block['signals'].get(name)
            if p is not None and (p >= floor_for(name)) == high:
                candidates.append((p if high else -p, v, block))
    candidates.sort(key=lambda item: -item[0])
    out, used = [], set()
    for _, v, block in candidates:
        if v in used:
            continue
        used.add(v)
        out.append(dict(video_id=v, start_seconds=block['start_seconds'], probability=block['signals'][name],
                        text=' '.join(block['text'].split())[:700]))
        if len(out) == limit:
            break
    return out


def rank(benchmark: str, chosen: Sequence[str], values: Mapping[str, Mapping[str, dict]],
         sermons_by_pastor: Mapping[str, Sequence[int]], scored, measured) -> list[dict]:
    """Every other pastor by mean absolute z difference from the benchmark on the chosen dimensions."""
    reference = [p for p in values if p != benchmark]
    scales = reference_scales(values, reference)
    target = {name: z(values[benchmark][name]['value'], name, scales) for name in chosen}
    rows = []
    for pastor in reference:
        diffs = []
        for name in chosen:
            zp = z(values[pastor][name]['value'], name, scales)
            if zp is not None and target[name] is not None:
                diffs.append(abs(zp - target[name]))
        if len(diffs) == len(chosen):
            rows.append(dict(pastor=pastor, distance=statistics.fmean(diffs),
                             values={n: values[pastor][n]['value'] for n in chosen}))
    rows.sort(key=lambda r: (r['distance'], r['pastor']))
    for row in rows[:SHORTLIST]:
        row['evidence'] = {n: evidence(n, sermons_by_pastor[row['pastor']], scored, measured,
                                       high=(target[n] or 0) > 0, limit=1) for n in chosen}
    return rows


def pair_distance_percentile(a: str, b: str, dimensions: Sequence[str], values: Mapping[str, Mapping[str, dict]]) -> dict:
    """Descriptive: where the a-b distance on the given dimensions falls among all pastor pairs."""
    pastors = sorted(values)
    scales = reference_scales(values, pastors)

    def distance(x: str, y: str) -> float | None:
        diffs = [abs(z(values[x][n]['value'], n, scales) - z(values[y][n]['value'], n, scales)) for n in dimensions
                 if z(values[x][n]['value'], n, scales) is not None and z(values[y][n]['value'], n, scales) is not None]
        return statistics.fmean(diffs) if diffs else None

    target = distance(a, b)
    others = [d for i, x in enumerate(pastors) for y in pastors[i + 1:] if (d := distance(x, y)) is not None]
    closer = sum(1 for d in others if d < target) if target is not None else None
    return dict(distance=target, pairs=len(others), pairs_closer=closer,
                percentile=(closer / len(others)) if target is not None and others else None,
                median_pair_distance=statistics.median(others) if others else None)


BREADTH_MIN_SHARE = 0.5      # on his side of the typical pastor in at least half of his sermons
CONCENTRATION_MAX = 0.6      # for a MORE trait counted in blocks: his top 3 sermons hold at most 60% of the hits


def breadth(row: Mapping, videos: Sequence[int], scored: Mapping[int, Mapping], measured: Mapping[int, Mapping]) -> dict:
    """Whether an explained dimension is a pattern across his sermons rather than a few of them (fixed 2026-11-24,
    before any result; replaces Brian's per-dimension mark at his request)."""
    name, more = row['dimension'], row['z'] > 0
    per = {}
    for video in videos:
        if name in free.DIMENSIONS:
            value = measured.get(video, {}).get(name)
            if value is not None:
                per[video] = dict(value=value)
        elif video in scored:
            blocks = scored[video]['blocks']
            hits = sum(1 for b in blocks if b['signals'].get(name, 0.0) >= floor_for(name))
            per[video] = dict(value=hits / len(blocks) if blocks else 0.0, hits=hits)
    median = row['pool_median']
    on_side = sum(1 for p in per.values() if (p['value'] > median if more else p['value'] < median))
    out = dict(sermons=len(per), on_his_side=on_side, breadth_ok=bool(per) and on_side / len(per) >= BREADTH_MIN_SHARE)
    if more and name not in free.DIMENSIONS:
        hits = sorted((p['hits'] for p in per.values()), reverse=True)
        total = sum(hits)
        out['top3_share'] = sum(hits[:3]) / total if total else None
        out['concentration_ok'] = bool(total) and sum(hits[:3]) / total <= CONCENTRATION_MAX
    else:
        out['concentration_ok'] = True
    out['pattern'] = out['breadth_ok'] and out['concentration_ok']
    return out

