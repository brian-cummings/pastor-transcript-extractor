"""Readable labels, review cards, verdicts (spec section 5) and the Markdown outputs."""
from __future__ import annotations

from ..bound_claims.common import watch_url
from . import EXPERIMENT, free

FAMILY = {'T': 'Topic', 'H': 'Style', 'L': 'Asks listeners to', 'M': 'Uses', 'S': 'Salvation', 'P': 'Public life'}
E1_TRUE_SHARE, E1_MAX_NOT_TRUE, E2_MIN_SUPPORTED = 0.75, 1, 4


def label(name: str) -> str:
    if name in free.DIMENSIONS:
        return free.DIMENSIONS[name][0]
    family, _, leaf = name.partition(':')
    return f"{FAMILY.get(family, family)}: {leaf.replace('_', ' ')}"


def meaning(name: str) -> str:
    """What Jev was asked for this dimension, in the pack's own wording ('' when there is none, e.g. free measures)."""
    family, _, leaf = name.partition(':')
    try:
        if family == 'T':
            from ..sermon_topics import TOPIC_SPECS
            return TOPIC_SPECS[leaf].definition
        if family == 'S':
            from ..sermon_salvation_relationships import SALVATION_RELATIONSHIP_SPECS
            return SALVATION_RELATIONSHIP_SPECS[leaf].description
        if family == 'H':
            from ..sermon_semantic_dimensions import SEMANTIC_DIMENSION_SPECS
            return SEMANTIC_DIMENSION_SPECS[leaf].description
        if family in ('P', 'L', 'M'):
            from ..sermon_leaf_packs import LISTENER_DIRECTIVES, PUBLIC_LIFE_TREATMENT, SOURCE_MATERIAL
            return {'P': PUBLIC_LIFE_TREATMENT, 'L': LISTENER_DIRECTIVES, 'M': SOURCE_MATERIAL}[family].definitions[leaf]
    except (KeyError, AttributeError):
        return ''
    return ''


def show(name: str, value) -> str:
    if value is None:
        return 'n/a'
    if name in free.DIMENSIONS:
        unit = free.DIMENSIONS[name][1]
        return f'{100 * value:.1f}%' if unit.startswith('share') else f'{value:.2f} {unit}'
    return f'{100 * value:.1f}% of preaching blocks'


def _direction(row) -> str:
    return 'more than' if row['z'] > 0 else 'less than'


def _evidence_lines(name: str, items, details) -> list[str]:
    lines = []
    for item in items:
        detail = details.get(item['video_id'], {'title': f"video {item['video_id']}", 'url': ''})
        if 'text' in item:
            link = watch_url(detail['url'], item['start_seconds']) if detail['url'] else ''
            lines += [f"> \"{item['text']}\"  \n> — *{detail['title']}* {link}", '']
        else:
            lines.append(f"- *{detail['title']}*: {show(name, item['sermon_value'])}")
    return lines


def dimension_card(name_of_pastor: str, row, details=None) -> str:
    details = details or {}
    lines = [f"{name_of_pastor} — {label(row['dimension'])}"]
    if meaning(row['dimension']):
        lines.append(f"  Means: a block that {meaning(row['dimension'])}" if row['dimension'][0] == 'P' else f"  Means: {meaning(row['dimension'])}")
    lines += [
             f"  {show(row['dimension'], row['value'])}, {_direction(row)} the typical pastor ({show(row['dimension'], row['pool_median'])}); "
             f"z {row['z']:+.1f}, halves {row['z_halves'][0]:+.1f} / {row['z_halves'][1]:+.1f}",
              f"  Question: is he {'more' if row['z'] > 0 else 'less'} given to this than most pastors, in your experience of him?"]
    for item in row.get('evidence', []):
        if 'text' in item:
            detail = details.get(item['video_id'])
            source = (f"\n    — {detail['title']} {watch_url(detail['url'], item['start_seconds'])}"
                      if detail and detail.get('url') else '')
            lines.append(f"  Example: \"{item['text'][:400]}\"{source}")
        else:
            lines.append(f"  Sermon value: {show(row['dimension'], item['sermon_value'])}")
    return '\n'.join(lines)


def explainer(explanations, names, details) -> str:
    lines = [f'# Benchmark explainer ({EXPERIMENT})', '',
             'What is distinctive (|z| at least 1.5 against the other pastors) and stable (both halves of his own sermons agree) '
             'about each benchmark. Jev values are the share of preaching blocks at or above the floor, never a probability. '
             'Spec: `docs/BENCHMARK_EXPLAINER.md`.', '']
    for benchmark, result in explanations.items():
        lines += [f"## {names[benchmark]} ({result['sermons']} sermons; halves {result['halves'][0]} and {result['halves'][1]})", '']
        if not result['explained']:
            lines += ['No dimension is both distinctive and stable.', '']
        for row in result['explained']:
            lines += [f"### {label(row['dimension'])}", '',
                      f"{show(row['dimension'], row['value'])}, {_direction(row)} the typical pastor "
                      f"({show(row['dimension'], row['pool_median'])}). z {row['z']:+.1f}; halves {row['z_halves'][0]:+.1f} and {row['z_halves'][1]:+.1f}.", '']
            lines += _evidence_lines(row['dimension'], row.get('evidence', []), details) + ['']
        if result['distinct_but_unstable']:
            lines += ['Distinctive but not stable across his sermons (not offered): '
                      + ', '.join(label(n) for n in result['distinct_but_unstable']), '']
    return '\n'.join(lines)


def pick_line(row) -> str:
    """One pick-list line: the dimension, its direction and the numbers, so a 'less than most' trait reads as one."""
    return (f"{label(row['dimension'])} — {'MORE' if row['z'] > 0 else 'LESS'} than most pastors "
            f"({show(row['dimension'], row['value'])} vs {show(row['dimension'], row['pool_median'])})")


def shortlist_card(names, benchmark, row, table, details) -> str:
    lines = [f"{names[row['pastor']]} for someone like {names[benchmark]} (distance {row['distance']:.2f})"]
    for name, value in row['values'].items():
        lines.append(f"  {label(name)}: {show(name, value)} (him: {show(name, table[benchmark][name]['value'])})")
        for item in row['evidence'].get(name, []):
            detail = details.get(item['video_id'], {})
            if 'text' in item:
                link = f" {watch_url(detail['url'], item['start_seconds'])}" if detail.get('url') else ''
                lines.append(f"    Example from \"{detail.get('title', '')}\"{link}: \"{item['text'][:350]}\"")
    lines.append(f"  Question: from these numbers and examples, is this pastor similar to {names[benchmark]} on these traits?")
    return '\n'.join(lines)


def verdicts(explanations, marks, ranks, pair, score_summary) -> dict:
    out = {'experiment': EXPERIMENT, 'spec': 'docs/BENCHMARK_EXPLAINER.md', 'benchmarks': {}, 'pair': pair,
           'jev_run': {k: score_summary[k] for k in ('failed_calls', 'incomplete_sermons', 'ledger')}}
    for benchmark, result in explanations.items():
        judged = [marks.get(f"{benchmark}/{r['dimension']}") for r in result['explained']]
        true, not_true = judged.count('true'), judged.count('not_true')
        can_judge = true + not_true
        e1 = bool(can_judge) and true / can_judge >= E1_TRUE_SHARE and not_true <= E1_MAX_NOT_TRUE
        judgments = ranks.get(benchmark, {}).get('judgments', {})
        supported = sum(v == 'supported' for v in judgments.values())
        out['benchmarks'][benchmark] = dict(
            explained=[r['dimension'] for r in result['explained']], marks=dict(zip([r['dimension'] for r in result['explained']], judged)),
            e1=dict(true=true, not_true=not_true, cannot_tell=judged.count('cannot_tell'), passed=e1),
            e2=dict(chosen=ranks.get(benchmark, {}).get('chosen', []), supported=supported, judged=len(judgments),
                    shortlist=[r['pastor'] for r in ranks.get(benchmark, {}).get('shortlist', [])],
                    passed=supported >= E2_MIN_SUPPORTED))
    return out


def report(result, names) -> str:
    mark = lambda ok: 'PASS' if ok else 'fail'
    lines = [f'# Benchmark explainer: report ({EXPERIMENT})', '', 'Pass marks fixed before the run (spec section 5).', '',
             '| Benchmark | E1 explanation (true / not / can\'t tell) | E2 ranking (supported of judged) |', '| --- | --- | --- |']
    for benchmark, row in result['benchmarks'].items():
        e1, e2 = row['e1'], row['e2']
        lines.append(f"| {names[benchmark]} | {mark(e1['passed'])} ({e1['true']} / {e1['not_true']} / {e1['cannot_tell']}) "
                     f"| {mark(e2['passed'])} ({e2['supported']} of {e2['judged']}) |")
    lines.append('')
    for benchmark, row in result['benchmarks'].items():
        lines += [f'## {names[benchmark]}', '']
        lines += [f"- {label(n)}: {m or 'not reviewed'}" for n, m in row['marks'].items()]
        if row['e2']['chosen']:
            lines += ['', 'Chosen for ranking: ' + ', '.join(label(n) for n in row['e2']['chosen']),
                      'Shortlist: ' + ', '.join(names[p] for p in row['e2']['shortlist'])]
        lines.append('')
    pair = result['pair']
    if pair and pair['distance'] is not None:
        lines += ['## Descriptive: Ty Gibson and David Asscherick', '',
                  f"Distance {pair['distance']:.2f} on the union of their stable dimensions; {pair['pairs_closer']} of {pair['pairs']} pastor pairs "
                  f"are closer (median pair {pair['median_pair_distance']:.2f}). Not a gate.", '']
    run = result['jev_run']
    lines += ['## Jev run', '', f"Failed pack calls: {run['failed_calls']}. Incomplete sermons: {len(run['incomplete_sermons'])}.", '']
    return '\n'.join(lines)


def trait_checks(result, names, details) -> str:
    lines = ['# Trait checks (benchmark-explainer-v1)', '',
             'Pattern: on his side of the typical pastor in at least half of his sermons, and (for MORE traits counted in '
             'blocks) his top 3 sermons hold at most 60% of the hits. Passages are for the content check.', '']
    for benchmark, rows in result.items():
        lines += [f'## {names[benchmark]}', '', '| Trait | Sermons on his side | Top-3 share | Pattern |', '| --- | --- | --- | --- |']
        for row in rows:
            share = f"{100 * row['top3_share']:.0f}%" if row.get('top3_share') is not None else '—'
            lines.append(f"| {label(row['dimension'])} ({'MORE' if row['z'] > 0 else 'LESS'}) | {row['on_his_side']} of {row['sermons']} | "
                         f"{share} | {'yes' if row['pattern'] else 'no'} |")
        lines.append('')
        for row in rows:
            if row.get('passages'):
                lines += [f"### {label(row['dimension'])}", '', f"Means: {meaning(row['dimension'])}", '']
                for item in row['passages']:
                    lines += [f"- *{details.get(item['video_id'], {}).get('title', item['video_id'])}* "
                              f"(p {item['probability']:.2f}): \"{item['text'][:500]}\"", '']
    return '\n'.join(lines)

