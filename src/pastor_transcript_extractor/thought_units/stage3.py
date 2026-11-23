"""Stage 3 of the snapped-unit test (docs/THOUGHT_UNIT_EXPERIMENT.md section 28.8): the pairs each arm reads, and the matched-record rule.

Arms: B2 = the 54 block pairs again (noise floor against the saved B1 run); U = the same pairs on their snapped unit; X1 = the same pairs on the one sub-unit of the
interior split that holds the pair's fixed target point; X2 = every sub-unit of the snapped unit (descriptive only). The pair keeps its block's leaf; only the text changes.
All inputs come from saved data (the snap results, the frozen target-point table); building them sends nothing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.bound_claims.common import digest, read_json, write_json
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal

from . import arms, leaf_evidence, public_set, snap

VERSION = 'stage3-pairs-v1'
ARM_KEYS = ('b2', 'u', 'x1', 'x2')
FROZEN_POINTS_SHA256 = '2c5292aac7c8f8c38dc3225bfb73cb573a1741ee4ec8d8d3b2a75d98a18675f1'     # section 28.9, written before any unit output existed
MATCH_SHARE = 0.5                                                                                # the record's anchor must overlap the point by half of the shorter span


def pairs_file(arm: str) -> str:
    return f'stage3/pairs-{arm}.json'


def _units(text: str, cuts: Sequence[int]) -> list[tuple[int, int]]:
    return snap.ranges_from_cuts(text, cuts)


def frozen_points(base_dir: Path, set_id: str = 'v2') -> list[dict[str, Any]]:
    table = read_json(public_set.set_dir(base_dir, set_id) / 'stage0-check.json')['points']
    if digest(table) != FROZEN_POINTS_SHA256:
        raise ValueError('The target-point table differs from the one frozen in section 28.9')
    return table


def block_range(result: Mapping[str, Any], blocks: Sequence[Sequence[Any]], ordinal: int, length: int) -> tuple[int, int] | None:
    """Where block `ordinal` lies after the snap, or None when an edge next to it was dropped (a merged unit is reported apart, never used)."""
    placed = {move['edge']: move['placed'] for move in result['placement']['moves']}
    dropped = set(result['placement']['dropped_edges'])
    if (ordinal > 0 and ordinal - 1 in dropped) or (ordinal < len(blocks) - 1 and ordinal in dropped):
        return None
    return (placed[ordinal - 1] if ordinal > 0 else 0, placed[ordinal] if ordinal < len(blocks) - 1 else length)


def _pair(source: Mapping[str, Any], *, key: str, unit: str, start: int, text: str, preceding: str, following: str, **extra: Any) -> dict[str, Any]:
    return dict(source, key=key, unit=unit, unit_start=start, text=text, preceding_text=preceding, following_text=following, **extra)


def build_pairs(base_dir: Path, set_id: str = 'v2') -> dict[str, Any]:
    """Write the four arms' sealed pairs files under the set's `stage3` folder and check every integrity rule of section 28.8; no provider call."""
    folder = public_set.set_dir(base_dir, set_id)
    block_pairs = leaf_evidence.pair_inputs(base_dir, leaf_evidence.CONFIRM3)          # B1's inputs: the 54 pairs
    points = {row['key']: row for row in frozen_points(base_dir, set_id)}
    if sorted(points) != sorted(p['key'] for p in block_pairs):
        raise ValueError('The frozen target points do not cover exactly the block pairs')
    arms_pairs: dict[str, list[dict[str, Any]]] = {name: [] for name in ARM_KEYS}
    apart = dict(merged=[], point_outside_unit=[], straddles_split=[], no_point=[], no_split=[])
    sermons: dict[int, Any] = {}
    for pair in block_pairs:
        video = int(pair['video_id'])
        if video not in sermons:
            sermon = public_set.load_sermon(base_dir, video, set_id)
            result = read_json(snap.set_snap_dir(base_dir, set_id, video) / 'snap_result.json')
            if seal(result) != result:
                raise ValueError(f'snap_result.json of sermon {video} seal differs')
            sermons[video] = (sermon, result, _units(sermon.text, result['arms']['jev']), _units(sermon.text, result['arms']['jev_split']))
        sermon, result, unit_ranges, split_ranges = sermons[video]
        arms_pairs['b2'].append(pair)
        ordinal = [b[0] for b in sermon.blocks].index(pair['unit'])
        span = block_range(result, sermon.blocks, ordinal, len(sermon.text))
        if span is None:
            apart['merged'].append(pair['key'])
            continue
        index = next(i for i, (a, b) in enumerate(unit_ranges) if span[0] <= a and b <= span[1])
        a, b = unit_ranges[index]
        around = lambda ranges, i, step: sermon.text[ranges[i + step][0]:ranges[i + step][1]] if 0 <= i + step < len(ranges) else ''
        arms_pairs['u'].append(_pair(pair, key=pair['key'], unit=pair['unit'], start=a, text=sermon.text[a:b], preceding=around(unit_ranges, index, -1),
                                     following=around(unit_ranges, index, 1)))
        inside = [i for i, (x, y) in enumerate(split_ranges) if a <= x and y <= b]
        if not inside:
            raise ValueError(f'No sub-unit lies inside the snapped unit of {pair["key"]}')
        if len(inside) == 1:
            apart['no_split'].append(pair['key'])
        for number, i in enumerate(inside):
            x, y = split_ranges[i]
            arms_pairs['x2'].append(_pair(pair, key=f"{pair['key']}.s{number}", unit=f"{pair['unit']}.s{number}", start=x, text=sermon.text[x:y],
                                          preceding=around(split_ranges, i, -1), following=around(split_ranges, i, 1), source_key=pair['key']))
        point = points[pair['key']]['point']
        if point is None:
            apart['no_point'].append(pair['key'])
            continue
        if not (a <= point['start'] and point['end'] <= b):
            apart['point_outside_unit'].append(pair['key'])      # the snap moved an edge across part of the block run's anchor: the unit cannot hold the whole point
            continue
        holder = [i for i in inside if split_ranges[i][0] <= point['start'] and point['end'] <= split_ranges[i][1]]
        if not holder:
            apart['straddles_split'].append(pair['key'])
            continue
        i = holder[0]
        x, y = split_ranges[i]
        arms_pairs['x1'].append(_pair(pair, key=pair['key'], unit=f"{pair['unit']}.s{inside.index(i)}", start=x, text=sermon.text[x:y],
                                      preceding=around(split_ranges, i, -1), following=around(split_ranges, i, 1)))
    # Section 24.6's rule, applied here before any output exists: a pair whose request cannot fit the provider's input cap (no truncation allowed) in ANY arm is
    # excluded from EVERY arm, by input size alone. Snapped units and their neighbors can be longer than the blocks they came from.
    unfit = {name: sorted({p.get('source_key', p['key']) for p in arms_pairs[name] if not leaf_evidence.fits_cap(p)}) for name in ARM_KEYS}
    excluded = sorted({key for keys in unfit.values() for key in keys})
    if excluded:
        arms_pairs = {name: [p for p in pairs if p.get('source_key', p['key']) not in excluded] for name, pairs in arms_pairs.items()}
        apart = {name: [k for k in keys if k not in excluded] for name, keys in apart.items()}
        apart['excluded_for_size'] = excluded
        apart['excluded_for_size_by_arm'] = unfit
    written = {}
    for name, pairs in arms_pairs.items():
        document = seal(dict(version=VERSION, arm=name, set_id=set_id, pairs=pairs, pairs_sha256=arms.pairs_digest(pairs)))
        write_json(folder / pairs_file(name), document)
        written[name] = dict(pairs=len(pairs), file=str(folder / pairs_file(name)), pairs_sha256=document['pairs_sha256'])
    return dict(arms=written, reported_apart={k: len(v) for k, v in apart.items() if isinstance(v, list)}, detail=apart)


# ---- the matched record ---------------------------------------------------------------------------------------------------

def overlap(first: tuple[int, int], second: tuple[int, int]) -> int:
    return max(0, min(first[1], second[1]) - max(first[0], second[0]))


def matched_record(claims: Sequence[Mapping[str, Any]], point: Mapping[str, int]) -> Mapping[str, Any] | None:
    """The record whose anchor overlaps the target point by at least half of the shorter span; the largest overlap when several do, the earlier record on a tie."""
    span = (point['start'], point['end'])
    best, best_overlap = None, 0
    for claim in claims:
        anchor = (claim['sermon_start'], claim['sermon_end'])
        shared = overlap(span, anchor)
        shorter = min(span[1] - span[0], anchor[1] - anchor[0])
        if shorter > 0 and shared >= MATCH_SHARE * shorter and shared > best_overlap:
            best, best_overlap = claim, shared
    return best
