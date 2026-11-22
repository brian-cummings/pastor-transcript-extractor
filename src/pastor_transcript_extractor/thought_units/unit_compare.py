"""Same-passage comparison of time blocks, snapped units and snapped units with splits (docs/THOUGHT_UNIT_EXPERIMENT.md section 22).

Section 16 compared each arm's accepted share on the passages that arm flagged, and the arms flagged different passages. Here a passage is fixed first: every
(leaf, span) any arm flagged under the frozen flag rule, merged when spans of the same leaf overlap. Each arm is then asked about that passage and leaf through the
unit of its own that holds it (its own flagged unit when it flagged one, else its unit with the largest overlap), with the same leaf-evidence instruction and the same
context rule. Offline: this module only builds the passage list and each arm's pair inputs; nothing here calls a provider.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from pastor_transcript_extractor.bound_claims.common import file_sha256, read_json, write_json
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal

from . import arms

VERSION = 'unit-compare-v1'
ARMS = ('b', 's', 'x')


def compare_dir(base_dir: Path, video: int = arms.VIDEO) -> Path:
    return arms.arms_paths(base_dir, video)['out'] / 'compare'


def clusters_path(base_dir: Path) -> Path:
    return compare_dir(base_dir) / 'clusters.json'


def overlap(unit: Mapping[str, Any], start: int, end: int) -> int:
    return max(0, min(unit['end'], end) - max(unit['start'], start))


def merge(items: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    """Group flagged (arm, unit, leaf, start, end) items: the same leaf and overlapping character spans are one passage."""
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, first in enumerate(items):
        for j in range(i):
            second = items[j]
            if first['leaf'] == second['leaf'] and first['start'] < second['end'] and second['start'] < first['end']:
                parent[find(i)] = find(j)
    groups: dict[int, list[Mapping[str, Any]]] = {}
    for i, item in enumerate(items):
        groups.setdefault(find(i), []).append(item)
    return sorted(groups.values(), key=lambda group: (min(g['start'] for g in group), group[0]['leaf']))


def evidence_unit(units: Sequence[Mapping[str, Any]], flagged_ids: Sequence[str], start: int, end: int) -> tuple[Mapping[str, Any], str]:
    """The arm's unit that holds the passage: its own flagged unit with the largest overlap, else its unit with the largest overlap."""
    own = [u for u in units if u['id'] in flagged_ids]
    pool, origin = (own, 'flagged') if own else (list(units), 'forced')
    best = max(pool, key=lambda u: (overlap(u, start, end), -u['ordinal']))
    if overlap(best, start, end) <= 0:
        raise ValueError('No unit of the arm overlaps the passage')
    return best, origin


def build(base_dir: Path) -> dict[str, Any]:
    units = arms.load_units(base_dir)['units']
    items = []
    for arm in ARMS:
        by_id = {u['id']: u for u in units[arm]}
        for pair in arms.flagged_pairs(units[arm], arms.signals_by_unit(base_dir, arm)):
            unit = by_id[pair['unit']]
            items.append(dict(arm=arm, unit=unit['id'], leaf=pair['leaf'], start=unit['start'], end=unit['end']))
    clusters, wanted = [], {arm: {} for arm in ARMS}
    for number, group in enumerate(merge(items), 1):
        leaf, start, end = group[0]['leaf'], min(g['start'] for g in group), max(g['end'] for g in group)
        evidence = {}
        for arm in ARMS:
            flagged = [g['unit'] for g in group if g['arm'] == arm]
            unit, origin = evidence_unit(units[arm], flagged, start, end)
            evidence[arm] = dict(unit=unit['id'], origin=origin, overlap=overlap(unit, start, end))
            wanted[arm][(unit['id'], leaf)] = None
        clusters.append(dict(id=f'p{number:02d}', leaf=leaf, start=start, end=end, flagged_by=sorted({g['arm'] for g in group}), evidence=evidence))
    result = seal(dict(version=VERSION, units_sha256=file_sha256(arms.arms_paths(base_dir)['units']),
                       flag_rule=dict(topic=arms.FLAG_TOPIC, topic_min=arms.FLAG_TOPIC_MIN, leaves=list(arms.FLAG_LEAVES), minimum=arms.FLAG_MIN, top=arms.FLAG_TOP),
                       clusters=clusters, pairs={arm: [dict(unit=u, leaf=l) for u, l in wanted[arm]] for arm in ARMS}))
    write_json(clusters_path(base_dir), result)
    return summary(result, str(clusters_path(base_dir)))


def summary(result: Mapping[str, Any], output: str) -> dict[str, Any]:
    clusters = result['clusters']
    return dict(output=output, passages=len(clusters), pairs={arm: len(p) for arm, p in result['pairs'].items()},
                flagged_by={'+'.join(key): sum(c['flagged_by'] == list(key) for c in clusters) for key in sorted({tuple(c['flagged_by']) for c in clusters})},
                forced_pairs={arm: sum(c['evidence'][arm]['origin'] == 'forced' for c in clusters) for arm in ARMS})


def load(base_dir: Path) -> dict[str, Any]:
    path = clusters_path(base_dir)
    if not path.exists():
        raise ValueError('Run `pte analysis thought-units compare-passages` first')
    result = read_json(path)
    if seal(result) != result:
        raise ValueError('clusters.json seal differs')
    if result['units_sha256'] != file_sha256(arms.arms_paths(base_dir)['units']):
        raise ValueError('clusters.json was built from different arm units')
    return result


def arm_pairs(base_dir: Path, arm: str) -> list[dict[str, Any]]:
    """One arm's pair inputs for the passages: its unit and the adjacent units (the pilot's context rule), exactly as the arm's own extraction would send them."""
    result = load(base_dir)
    units = arms.load_units(base_dir)['units'][arm]
    by_id = {u['id']: u for u in units}
    signals = arms.signals_by_unit(base_dir, arm)
    pairs = []
    for item in result['pairs'][arm]:
        unit = by_id[item['unit']]
        probability = signals.get(unit['id'], {}).get(item['leaf'])
        pairs.append(dict(unit=unit['id'], leaf=item['leaf'], probability=probability, topic=signals.get(unit['id'], {}).get(arms.FLAG_TOPIC),
                          key=f"{arm}:{unit['id']}-{item['leaf'].removeprefix('P:')}", unit_start=unit['start'], text=unit['text'],
                          preceding_text=units[unit['ordinal'] - 1]['text'] if unit['ordinal'] else '',
                          following_text=units[unit['ordinal'] + 1]['text'] if unit['ordinal'] + 1 < len(units) else ''))
    return pairs
