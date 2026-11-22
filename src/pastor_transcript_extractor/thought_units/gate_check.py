"""Precision of the Jev leaf gate (docs/THOUGHT_UNIT_EXPERIMENT.md section 26). Offline: nothing here calls a provider.

The frozen flag rule sends a (unit, leaf) pair to the extractor when Jev scores the topic at least 0.9 and the leaf at least 0.8. About a fifth of the pairs turned out not to show the leaf
(section 24.7). This module grades, for every flagged pair of both sets and blind to the Jev score and to any extraction, whether the unit really shows the leaf.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable, Mapping

from pastor_transcript_extractor.bound_claims.common import digest, read_json, write_json
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal

from . import leaf_evidence, leaf_review, main_point, public_set, stage

VERSION = 'gate-check-v1'
LEVELS = dict(y='shows', b='borderline', n='does_not_show')
SETS = ('v1', 'v2')
BAND_CUT = 0.90                 # section 26.2 reading 3
PRECISION_BAR = 0.80            # section 26.2 decision rule
INFORMATIVE_POINTS = 0.15
SECOND_RATER_PAIRS = 12
CONTEXT = 700                   # characters of each neighboring unit shown


def gate_dir(base_dir: Path) -> Path:
    return stage.paths(base_dir)[2] / 'gate-check'


def paths_for(base_dir: Path, rater: str = 'main') -> dict[str, Path]:
    out = gate_dir(base_dir)
    suffix = '' if rater == 'main' else f'-{rater}'
    return dict(out=out, queue=out / f'queue{suffix}.json', versions=out / 'versions.json', decisions=out / f'decisions{suffix}.jsonl',
                report_md=out / 'GATE_CHECK.md', report_json=out / 'GATE_CHECK.json')


def census(base_dir: Path) -> list[dict[str, Any]]:
    """Every flagged pair of both sets (the three-leaf pair files), each with the unit and its neighbors and the Jev score kept apart."""
    rows = []
    for set_id in SETS:
        for pair in public_set.half_pairs(base_dir, 'all', 'pairs-top3.json', set_id):
            rows.append(dict(pair, set=set_id, pair_id=digest(dict(set=set_id, key=pair['key']))[:16], unit_key=f"{set_id}:{pair['video_id']}:{pair['unit']}"))
    return rows


def build(base_dir: Path) -> dict[str, Any]:
    rows, paths = census(base_dir), paths_for(base_dir)
    units: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda r: digest(r['pair_id'])):
        unit = units.setdefault(row['unit_key'], dict(unit_key=digest(row['unit_key'])[:16], unit_text=row['text'], preceding_text=row['preceding_text'][-CONTEXT:],
                                                       following_text=row['following_text'][:CONTEXT], leaves=[]))
        unit['leaves'].append(dict(id=row['pair_id'], leaf=row['leaf'], leaf_meaning=main_point.leaf_meaning(row['leaf'])))
    items = sorted(units.values(), key=lambda u: digest(u['unit_key']))
    queue = seal(dict(version=VERSION, item_count=len(items), pairs=len(rows), items=items))
    versions = seal(dict(version=VERSION, queue_fingerprint=queue['content_fingerprint'],
                         pairs={r['pair_id']: dict(set=r['set'], key=r['key'], leaf=r['leaf'], probability=r['probability'], topic=r.get('topic'), video_id=r['video_id']) for r in rows}))
    paths['out'].mkdir(parents=True, exist_ok=True)
    write_json(paths['queue'], queue)
    write_json(paths['versions'], versions)
    return dict(queue=str(paths['queue']), units=len(items), pairs=len(rows), by_set={s: sum(r['set'] == s for r in rows) for s in SETS})


def second_rater_queue(base_dir: Path) -> dict[str, Any]:
    """Units chosen by rule (sha256 of the unit key, in order) until at least SECOND_RATER_PAIRS pairs are covered; every leaf of a chosen unit is asked."""
    full = leaf_review._sealed(paths_for(base_dir)['queue'])
    chosen, covered = [], 0
    for unit in sorted(full['items'], key=lambda u: digest(u['unit_key'])):
        if covered >= SECOND_RATER_PAIRS:
            break
        chosen.append(unit)
        covered += len(unit['leaves'])
    queue = seal(dict(version=VERSION, item_count=len(chosen), pairs=covered, items=chosen))
    paths = paths_for(base_dir, 'second')
    write_json(paths['queue'], queue)
    return dict(queue=str(paths['queue']), units=len(chosen), pairs=covered)


def render(unit: Mapping[str, Any], number: int, total: int, leaf: Mapping[str, Any]) -> str:
    return (f"\n[unit {number}/{total}]\n[PRECEDING TEXT] {unit['preceding_text']}\n\nUNIT: {unit['unit_text']}\n\n[FOLLOWING TEXT] {unit['following_text']}\n\n"
            f"LEAF {leaf['leaf']}: {leaf['leaf_meaning']}")


QUESTION = 'Does the UNIT itself show this leaf as defined: yes (y), borderline (b: weaker, partial, or an exclusion nearly applies) or no (n)? '


def judge(base_dir: Path, source: str = 'human', rater: str = 'main', input_fn=input, output_fn=print) -> dict[str, Any]:
    paths = paths_for(base_dir, rater)
    if not paths['queue'].exists():
        (build if rater == 'main' else second_rater_queue)(base_dir)
    queue = leaf_review._sealed(paths['queue'])
    for number, unit in enumerate(queue['items'], 1):
        for leaf in unit['leaves']:
            if leaf['id'] in leaf_review.load_decisions(base_dir, leaf_evidence.V2, paths):
                continue
            output_fn(render(unit, number, queue['item_count'], leaf))
            while (said := input_fn(QUESTION).strip().lower()) not in LEVELS:
                output_fn('Answer y, b or n.')
            leaf_review.record_decision(base_dir, leaf['id'], source, leaf_evidence.V2, paths, level=LEVELS[said])
    return progress(base_dir, rater)


def progress(base_dir: Path, rater: str = 'main') -> dict[str, Any]:
    paths = paths_for(base_dir, rater)
    queue, decided = leaf_review._sealed(paths['queue']), leaf_review.load_decisions(base_dir, leaf_evidence.V2, paths)
    ids = [leaf['id'] for unit in queue['items'] for leaf in unit['leaves']]
    return dict(pairs=len(ids), decided=sum(i in decided for i in ids), remaining=sum(i not in decided for i in ids), decisions_file=str(paths['decisions']))


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    if not total:
        return None
    p = successes / total
    centre, margin = (p + z * z / (2 * total)) / (1 + z * z / total), z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return round(centre - margin, 3), round(centre + margin, 3)


def measures(info: Mapping[str, Mapping[str, Any]], decided: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Pure: the section 26.2 readings from the pair table (set, leaf, probability) and the labels."""
    def tally(ids) -> dict[str, Any]:
        ids = list(ids)
        yes = sum(decided[i]['level'] == 'shows' for i in ids)
        border = sum(decided[i]['level'] == 'borderline' for i in ids)
        return dict(pairs=len(ids), shows=yes, borderline=border, does_not_show=len(ids) - yes - border,
                    strict=round(yes / len(ids), 3) if ids else None, lenient=round((yes + border) / len(ids), 3) if ids else None,
                    strict_interval=wilson(yes, len(ids)), lenient_interval=wilson(yes + border, len(ids)))
    ids = list(info)
    high, low = [i for i in ids if info[i]['probability'] >= BAND_CUT], [i for i in ids if info[i]['probability'] < BAND_CUT]
    overall, top, bottom = tally(ids), tally(high), tally(low)
    informative = None if not high or not low else (top['strict'] - bottom['strict']) >= INFORMATIVE_POINTS - 1e-9
    return dict(overall=overall, by_leaf={leaf: tally(i for i in ids if info[i]['leaf'] == leaf) for leaf in sorted({info[i]['leaf'] for i in ids})},
                by_band={f'>= {BAND_CUT}': top, f'< {BAND_CUT}': bottom}, by_set={s: tally(i for i in ids if info[i]['set'] == s) for s in SETS},
                probability_informative=informative, gate_meets_bar=overall['strict'] is not None and overall['strict'] + 1e-9 >= PRECISION_BAR)


def report(base_dir: Path) -> dict[str, Any]:
    paths = paths_for(base_dir)
    queue, versions = leaf_review._sealed(paths['queue']), leaf_review._sealed(paths['versions'])
    decided = leaf_review.load_decisions(base_dir, leaf_evidence.V2, paths)
    missing = [i for i in versions['pairs'] if i not in decided]
    if missing:
        raise ValueError(f'{len(missing)} pairs are unlabeled')
    result = dict(version=VERSION, **measures(versions['pairs'], decided), labels_by=sorted({d['source'] for d in decided.values()}))
    if paths_for(base_dir, 'second')['decisions'].exists():
        second = leaf_review.load_decisions(base_dir, leaf_evidence.V2, paths_for(base_dir, 'second'))
        shared = [i for i in second if i in decided]
        result['second_rater'] = dict(pairs=len(shared), agree=sum(second[i]['level'] == decided[i]['level'] for i in shared),
                                      agree_strict=sum((second[i]['level'] == 'shows') == (decided[i]['level'] == 'shows') for i in shared))
    result['not_showing'] = [dict(set=versions['pairs'][i]['set'], key=versions['pairs'][i]['key'], leaf=versions['pairs'][i]['leaf'], probability=versions['pairs'][i]['probability'])
                             for i in versions['pairs'] if decided[i]['level'] == 'does_not_show']
    write_json(paths['report_json'], result)
    o = result['overall']
    lines = ['# Leaf-gate precision (section 26)', '', f"{o['pairs']} flagged pairs: shows {o['shows']}, borderline {o['borderline']}, does not show {o['does_not_show']}; strict precision {o['strict']} {o['strict_interval']}, lenient {o['lenient']} {o['lenient_interval']}.",
             f"Bar (strict at least {PRECISION_BAR:.0%}): {'met' if result['gate_meets_bar'] else 'not met'}. Probability informative (band difference at least {INFORMATIVE_POINTS:.0%}): {result['probability_informative']}.", '',
             '| Group | Pairs | Shows | Borderline | No | Strict |', '| --- | --- | --- | --- | --- | --- |']
    for title, group in (('leaf', result['by_leaf']), ('band', result['by_band']), ('set', result['by_set'])):
        lines += [f"| {title} {name} | {t['pairs']} | {t['shows']} | {t['borderline']} | {t['does_not_show']} | {t['strict']} |" for name, t in group.items()]
    lines += ['', f"Labels by {result['labels_by']}." + (f" Second rater: {result['second_rater']}." if 'second_rater' in result else ''), '']
    paths['report_md'].write_text('\n'.join(lines))
    return dict(result, report_md=str(paths['report_md']), report_json=str(paths['report_json']))
