"""Blind review and report of the Stage 3 unit test (docs/THOUGHT_UNIT_EXPERIMENT.md section 28.8 and 28.13).

Arms: b1 (the saved v4 block run), b2 (blocks again), u (snapped units), x1 (the sub-unit holding the target point), x2 (every sub-unit, descriptive).
Each pair's target point is the frozen table of 28.9. The record graded for an arm is the one whose anchor overlaps the point (`stage3.matched_record`). Records are shown
version-blind, grouped by pair under one shared reference span (the block span united with the snapped unit's span, plus WINDOW characters either side); an identical
record found by several arms is one item and is graded once. Labels are evaluation labels with a source; nothing here changes an earlier label.
"""
from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.bound_claims.common import digest, read_json, write_json
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal

from . import gate_check, leaf_evidence, leaf_review, main_point, public_set, set_review, stage3

VERSION = 'stage3-review-v1'
ARMS = ('b1', 'b2', 'u', 'x1')              # arms with a matched record per pair
MULTI_ARMS = (*ARMS, 'x2')                  # x2 is only read for records per pair and distinct points
WINDOW = set_review.SPOT_WINDOW
LEVELS = dict(c='complete', a='accurate_incomplete', w='wrong')
FOCUS = dict(p='on_point', b='blended')
DISTINCT = dict(d='distinct', o='overlapping', s='same_point_twice')
OUTCOME = dict(complete=3, accurate_incomplete=2, none=1, wrong=0)        # 28.8: wrong is the worst outcome, no record the next
ALPHA, MIN_DISCORDANT = 0.10, 10
ACCURACY_BAR, FLAG_LIMIT, RECALL_SHARE, FRAGMENT_MARGIN, SAME_POINT_LIMIT, MIN_MULTI = 0.90, 0.15, 0.90, 0.10, 0.15, 12
SAMPLE_PER_ARM, BOOTSTRAP, BOOTSTRAP_SEED = 6, 2000, 20251122


def paths(base_dir: Path, set_id: str = 'v2') -> dict[str, Path]:
    folder = public_set.set_dir(base_dir, set_id) / 'stage3'
    return dict(folder=folder, queue=folder / 'review-queue.json', versions=folder / 'review-versions.json', decisions=folder / 'decisions.jsonl',
                sample=folder / 'review-sample.json', human=folder / 'decisions-human.jsonl', second=folder / 'decisions-second.jsonl', report_md=folder / 'STAGE3_REPORT.md', report_json=folder / 'STAGE3_REPORT.json')


# ---- what each arm returned -------------------------------------------------------------------------------------------------

EXTRACTIONS = dict(b1='leaf-evidence-b4-confirm-top3', b2='leaf-evidence-b4-stage3-b2', u='leaf-evidence-b4-stage3-u', x1='leaf-evidence-b4-stage3-x1', x2='leaf-evidence-b4-stage3-x2')


def load_arm(base_dir: Path, arm: str, set_id: str = 'v2') -> list[dict[str, Any]]:
    """One entry per request of an arm, in order: the pair as sent, and what came back (`state` is record, no_record or missing)."""
    folder = public_set.set_dir(base_dir, set_id)
    pairs = read_json(folder / stage3.pairs_file('b2' if arm == 'b1' else arm))['pairs']
    rows = read_json(folder / EXTRACTIONS[arm] / 'extraction.json')['rows']
    if len(pairs) != len(rows) or any(p['unit'] != r['unit'] or p['leaf'] != r['leaf'] for p, r in zip(pairs, rows)):
        raise ValueError(f'The {arm} extraction does not line up with its pairs')
    entries = []
    for pair, row in zip(pairs, rows):
        state = 'missing' if row['status'] in ('transport_failure', 'lost_attempt') else ('record' if row['claims'] else 'no_record')     # a schema failure is a failed extraction: no record
        entries.append(dict(pair=pair, source=pair.get('source_key', pair['key']), state=state, claims=row['claims'], span=(pair['unit_start'], pair['unit_start'] + len(pair['text']))))
    return entries


def point_table(base_dir: Path, set_id: str = 'v2') -> dict[str, dict[str, Any]]:
    return {row['key']: row for row in stage3.frozen_points(base_dir, set_id)}


def block_of(key: str) -> str:
    video, unit = key.split('-')[:2]
    return f'{video}-{unit}'


def cut(point: Mapping[str, int], span: tuple[int, int]) -> bool:
    """Deterministic (28.11): the point is cut when it does not lie wholly inside the request's text."""
    return not (span[0] <= point['start'] and point['end'] <= span[1])


def matched(base_dir: Path, set_id: str = 'v2') -> dict[str, dict[str, dict[str, Any]]]:
    """arm -> pair key -> dict(state, claim, cut, video): only pairs that have a target point."""
    points = point_table(base_dir, set_id)
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for arm in ARMS:
        result[arm] = {}
        for entry in load_arm(base_dir, arm, set_id):
            key, row = entry['source'], points[entry['source']]
            if row['point'] is None:
                continue
            claim = stage3.matched_record(entry['claims'], row['point']) if entry['state'] == 'record' else None
            state = 'missing' if entry['state'] == 'missing' else ('record' if claim else 'no_record')
            result[arm][key] = dict(state=state, claim=claim, cut=cut(row['point'], entry['span']), video=row['video_id'], records=len(entry['claims']))
    return result


# ---- the blind queue --------------------------------------------------------------------------------------------------------

def item_id(key: str, claim: Mapping[str, Any]) -> str:
    return digest(['record', key, claim['summary'], claim['claim']['proposition'], claim['sermon_start'], claim['sermon_end']])


def build(base_dir: Path, set_id: str = 'v2') -> dict[str, Any]:
    folder = public_set.set_dir(base_dir, set_id)
    points, table = point_table(base_dir, set_id), matched(base_dir, set_id)
    block_pairs = {p['key']: p for p in read_json(folder / stage3.pairs_file('b2'))['pairs']}
    unit_pairs = {p['key']: p for p in read_json(folder / stage3.pairs_file('u'))['pairs']}
    versions: dict[str, list[str]] = {}
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for key in points:
        if points[key]['point'] is None:
            continue
        for arm in ARMS:
            claim = table[arm].get(key, {}).get('claim')
            if not claim:
                continue
            iid = item_id(key, claim)
            if iid not in versions:
                record = claim['claim']
                versions[iid] = []
                by_pair.setdefault(key, []).append(dict(id=iid, kind='record', group=key, summary=claim['summary'], proposition=record['proposition'], target=claim['target'],
                                                        conditions=record['conditions'], qualifications=record['qualifications'], reasons=record['reasons'], anchor_text=record['anchor_text']))
            versions[iid].append(arm)
    multi = distinct_items(base_dir, set_id, versions)
    for item in multi:
        by_pair.setdefault(item['group'], [])
    sermons: dict[int, Any] = {}
    groups, items = [], []
    for key in sorted(by_pair, key=digest):
        block, unit, point = block_pairs[key], unit_pairs[key], points[key]['point']
        video = int(block['video_id'])
        if video not in sermons:
            sermons[video] = public_set.load_sermon(base_dir, video, set_id)
        text = sermons[video].text
        start, end = min(block['unit_start'], unit['unit_start']), max(block['unit_start'] + len(block['text']), unit['unit_start'] + len(unit['text']))
        if point:
            start, end = min(start, point['start']), max(end, point['end'])
        lo, hi = max(0, start - WINDOW), min(len(text), end + WINDOW)
        passage = (text[lo:point['start']] + '⟦POINT⟧' + text[point['start']:point['end']] + '⟦/POINT⟧' + text[point['end']:hi]) if point else text[lo:hi]
        mine = sorted(by_pair[key], key=lambda i: digest(i['id']))
        groups.append(dict(key=key, leaf=block['leaf'], leaf_meaning=main_point.leaf_meaning(block['leaf']), passage=passage, has_point=bool(point),
                           watch_url=sermons[video].link_at(point['start'] if point else block['unit_start']), record_ids=[i['id'] for i in mine]))
        items.extend(mine)
        items.extend(i for i in multi if i['group'] == key)
    queue = seal(dict(version=VERSION, set_id=set_id, window=WINDOW, item_count=len(items), groups=groups, items=items))
    out = paths(base_dir, set_id)
    write_json(out['queue'], queue)
    write_json(out['versions'], seal(dict(version=VERSION, arms={k: sorted(v) for k, v in versions.items()})))
    return dict(queue=str(out['queue']), groups=len(groups), items=len(items), record_items=sum(i['kind'] == 'record' for i in items),
                distinct_items=sum(i['kind'] == 'distinct' for i in items), arms_sharing_a_record=sum(len(v) > 1 for v in versions.values() if v and v[0] in ARMS))


def distinct_items(base_dir: Path, set_id: str, versions: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Pairs for which an arm returned two or more records (for x2: across the sub-units of the pair): are they distinct points? One item per distinct set of summaries."""
    items: dict[str, dict[str, Any]] = {}
    for arm in MULTI_ARMS:
        by_pair: dict[str, list[Mapping[str, Any]]] = {}
        for entry in load_arm(base_dir, arm, set_id):
            by_pair.setdefault(entry['source'], []).extend(entry['claims'])
        for key, claims in by_pair.items():
            if len(claims) < 2:
                continue
            iid = digest(['distinct', key, sorted(c['summary'] for c in claims)])
            items.setdefault(iid, dict(id=iid, kind='distinct', group=key, summaries=[c['summary'] for c in claims], anchors=[c['claim']['anchor_text'] for c in claims]))
            versions.setdefault(iid, []).append(arm)
    return sorted(items.values(), key=lambda i: digest(i['id']))


SECOND_GROUPS = 12


def second_groups(queue: Mapping[str, Any]) -> list[str]:
    """The second rater's pairs by rule (28.14): the first SECOND_GROUPS pair keys in sha256 order, with every item of those pairs."""
    return sorted((g['key'] for g in queue['groups']), key=digest)[:SECOND_GROUPS]


def second_agreement(queue: Mapping[str, Any], main: Mapping[str, Mapping[str, Any]], second: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The second rater against the rater of record on the items both labeled: level agreement for every item, focus and fit for records, and the disagreements."""
    items = [i for i in queue['items'] if i['id'] in second and i['id'] in main]
    records = [i for i in items if i['kind'] == 'record']
    same = lambda field, rows: sum(main[i['id']].get(field) == second[i['id']].get(field) for i in rows)
    return dict(items=len(items), level_agree=same('level', items), records=len(records), focus_agree=same('focus', records), fit_agree=same('fit', records),
                disagreements=[dict(item=i['id'][:10], kind=i['kind'], main=main[i['id']]['level'], second=second[i['id']]['level']) for i in items
                               if main[i['id']]['level'] != second[i['id']]['level']])


def sample_ids(queue: Mapping[str, Any], versions: Mapping[str, Any]) -> list[str]:
    """Brian's sample by rule (28.8): the first SAMPLE_PER_ARM record items of u and of x1 in sha256 order of the item id, so both arms are covered; version-blind on screen."""
    chosen: list[str] = []
    for arm in ('u', 'x1'):
        pool = sorted((i['id'] for i in queue['items'] if i['kind'] == 'record' and arm in versions['arms'][i['id']]), key=digest)
        chosen += [i for i in pool if i not in chosen][:SAMPLE_PER_ARM]
    return chosen


def build_sample(base_dir: Path, set_id: str = 'v2') -> dict[str, Any]:
    out = paths(base_dir, set_id)
    queue, versions = leaf_review._sealed(out['queue']), leaf_review._sealed(out['versions'])
    ids = sample_ids(queue, versions)
    groups = {g['key'] for g in queue['groups'] if any(i in ids for i in g['record_ids'])}
    sample = seal(dict(version=VERSION, source_sha256=queue['content_fingerprint'], item_count=len(ids), groups=[g for g in queue['groups'] if g['key'] in groups],
                       items=[i for i in queue['items'] if i['id'] in ids]))
    write_json(out['sample'], sample)
    return dict(sample=str(out['sample']), items=len(ids))


# ---- showing and judging ----------------------------------------------------------------------------------------------------

def render(item: Mapping[str, Any], group: Mapping[str, Any], number: int, total: int, first_of_group: bool) -> str:
    head = ''
    if first_of_group:
        head = f"\n{'=' * 78}\nPAIR {group['key']}   {group['watch_url']}\nLEAF {group['leaf']}: {group['leaf_meaning']}\n\n{group['passage']}\n{'-' * 78}"
    if item['kind'] == 'distinct':
        body = '\n'.join(f'  {n}. {s}' for n, s in enumerate(item['summaries'], 1))
        return f'{head}\n[{number}/{total}] RECORDS OF THIS PAIR:\n{body}'
    lines = [f'{head}\n[{number}/{total}] SUMMARY: {item["summary"]}', f'PROPOSITION: {item["proposition"]}', f'TARGET: {item["target"]}']
    lines += [name.upper() + ': ' + ('; '.join(item[name]) or '(none)') for name in ('conditions', 'qualifications', 'reasons')]
    return '\n'.join(lines + ['ANCHOR: «' + item['anchor_text'] + '»'])


QUESTIONS = dict(level='Level: complete (c), accurate but incomplete (a), wrong (w)? ',
                 flag="Is the omitted material the preacher's own objection, ground or condition for the point (y/n)? ",
                 focus='Focus: on the point only (p) or blended with another point of the unit (b)? ',
                 fit='Does the record state what the leaf definition describes (y/n)? ',
                 framed="Does the summary state the leaf's own act as the definition describes it (y/n)? ",
                 distinct='Are the records distinct (d), overlapping (o) or the same point twice (s)? ')


def _ask(prompt: str, allowed: Mapping[str, str], input_fn: Callable[[str], str], output_fn: Callable[[str], Any]) -> str:
    while True:
        said = input_fn(prompt).strip().lower()
        if said in allowed:
            return said
        output_fn('Answer one of: ' + ', '.join(allowed) + '.')


def judge(base_dir: Path, *, human: bool, set_id: str = 'v2', input_fn: Callable[[str], str] = input, output_fn: Callable[[str], Any] = print) -> dict[str, Any]:
    out = paths(base_dir, set_id)
    queue = leaf_review._sealed(out['sample'] if human else out['queue'])
    files = dict(decisions=out['human'] if human else out['decisions'])
    source = 'human' if human else 'claude'
    groups, decided, seen = {g['key']: g for g in queue['groups']}, leaf_review.load_decisions(base_dir, leaf_evidence.V4, files), set()
    yn = dict(y='', n='')
    for number, item in enumerate(queue['items'], 1):
        first = item['group'] not in seen
        seen.add(item['group'])
        if item['id'] in decided:
            continue
        output_fn(render(item, groups[item['group']], number, queue['item_count'], first))
        if item['kind'] == 'distinct':
            leaf_review.record_decision(base_dir, item['id'], source, leaf_evidence.V4, files, level=DISTINCT[_ask(QUESTIONS['distinct'], DISTINCT, input_fn, output_fn)])
            continue
        level = LEVELS[_ask(QUESTIONS['level'], LEVELS, input_fn, output_fn)]
        flag = _ask(QUESTIONS['flag'], yn, input_fn, output_fn) == 'y' if level == 'accurate_incomplete' else False
        focus = FOCUS[_ask(QUESTIONS['focus'], FOCUS, input_fn, output_fn)] if level != 'wrong' else 'on_point'
        fit = _ask(QUESTIONS['fit'], yn, input_fn, output_fn) == 'y'
        framed = _ask(QUESTIONS['framed'], yn, input_fn, output_fn) == 'y'
        leaf_review.record_decision(base_dir, item['id'], source, leaf_evidence.V4, files, level=level, flag=flag, focus=focus, fit=fit, framed=framed)
    return progress(base_dir, human=human, set_id=set_id)


def progress(base_dir: Path, *, human: bool, set_id: str = 'v2') -> dict[str, Any]:
    out = paths(base_dir, set_id)
    queue = leaf_review._sealed(out['sample'] if human else out['queue'])
    decided = leaf_review.load_decisions(base_dir, leaf_evidence.V4, dict(decisions=out['human'] if human else out['decisions']))
    return dict(items=queue['item_count'], decided=sum(i['id'] in decided for i in queue['items']), remaining=sum(i['id'] not in decided for i in queue['items']))


# ---- the readings (pure) ----------------------------------------------------------------------------------------------------

def sign_p(wins: int, losses: int) -> float | None:
    """One-sided: the probability of at least `wins` wins among wins + losses discordant blocks under a fair coin."""
    n = wins + losses
    return None if n == 0 else sum(math.comb(n, k) for k in range(wins, n + 1)) / 2 ** n


def pair_outcomes(table: Mapping[str, Mapping[str, Mapping[str, Any]]], decided: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """arm -> pair key -> dict(outcome, record fields, cut, video); missing requests are left out of the arm."""
    result: dict[str, dict[str, Any]] = {}
    for arm, pairs in table.items():
        result[arm] = {}
        for key, cell in pairs.items():
            if cell['state'] == 'missing':
                continue
            if cell['state'] == 'no_record':
                result[arm][key] = dict(outcome=OUTCOME['none'], level='none', cut=cell['cut'], video=cell['video'])
                continue
            label = decided[item_id(key, cell['claim'])]
            result[arm][key] = dict(outcome=OUTCOME[label['level']], level=label['level'], flag=bool(label.get('flag')), focus=label.get('focus'), fit=bool(label.get('fit')),
                                    framed=bool(label.get('framed')), cut=cell['cut'], video=cell['video'])
    return result


def compare(outcomes: Mapping[str, Mapping[str, Any]], first: str, second: str, exclude_video: int | None = None) -> dict[str, Any]:
    """Block-level paired comparison of `first` against `second` over pairs both arms answered: block means, the sign of the difference, ties left out."""
    shared = [k for k in outcomes[first] if k in outcomes[second] and (exclude_video is None or outcomes[first][k]['video'] != exclude_video)]
    blocks: dict[str, list[tuple[int, int, int]]] = {}
    for key in shared:
        blocks.setdefault(block_of(key), []).append((outcomes[first][key]['outcome'], outcomes[second][key]['outcome'], outcomes[first][key]['video']))
    diffs = {b: (sum(x for x, _, _ in v) - sum(y for _, y, _ in v)) / len(v) for b, v in blocks.items()}
    wins, losses = sum(d > 0 for d in diffs.values()), sum(d < 0 for d in diffs.values())
    video = {b: v[0][2] for b, v in blocks.items()}
    return dict(pairs=len(shared), blocks=len(blocks), wins=wins, losses=losses, ties=len(diffs) - wins - losses, mean_difference=(sum(diffs.values()) / len(diffs)) if diffs else None,
                p_first_better=sign_p(wins, losses), p_second_better=sign_p(losses, wins), bootstrap=cluster_bootstrap(diffs, video))


def cluster_bootstrap(diffs: Mapping[str, float], video: Mapping[str, int]) -> list[float] | None:
    """Description only: a 95% interval for the mean block difference, resampling whole sermons with a fixed seed."""
    clusters: dict[int, list[float]] = {}
    for block, value in diffs.items():
        clusters.setdefault(video[block], []).append(value)
    if len(clusters) < 2:
        return None
    rng, means, keys = random.Random(BOOTSTRAP_SEED), [], list(clusters)
    for _ in range(BOOTSTRAP):
        sample = [v for k in (rng.choice(keys) for _ in keys) for v in clusters[k]]
        means.append(sum(sample) / len(sample))
    means.sort()
    return [round(means[int(0.025 * BOOTSTRAP)], 3), round(means[int(0.975 * BOOTSTRAP)], 3)]


def verdict(comparisons: Sequence[Mapping[str, Any]], better: str = 'p_first_better', worse: str = 'p_second_better') -> str:
    """28.8: improved if the one-sided sign p is at most ALPHA against every comparison with more wins than losses; harmed in the reverse; inconclusive below MIN_DISCORDANT."""
    if any(c['wins'] + c['losses'] < MIN_DISCORDANT for c in comparisons):
        return 'inconclusive'
    if all(c[better] is not None and c[better] <= ALPHA and c['wins'] > c['losses'] for c in comparisons):
        return 'improved'
    if all(c[worse] is not None and c[worse] <= ALPHA and c['losses'] > c['wins'] for c in comparisons):
        return 'harmed'
    return 'not shown'


def arm_summary(arm_outcomes: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(arm_outcomes.values())
    n = len(rows)
    records = [r for r in rows if r['level'] != 'none']
    share = lambda k, total: (k / total) if total else None
    level = lambda name: sum(r['level'] == name for r in rows)
    return dict(pairs=n, complete=level('complete'), accurate_incomplete=level('accurate_incomplete'), wrong=level('wrong'), no_record=level('none'), records=len(records),
                accuracy=share(len(records) - level('wrong'), len(records)), accuracy_interval=gate_check.wilson(len(records) - level('wrong'), len(records)),
                recall=share(len(records), n), flagged_share=share(sum(r.get('flag', False) for r in records), len(records)),
                blended_share=share(sum(r.get('focus') == 'blended' for r in records), len(records)), misfit_share=share(sum(not r.get('fit', True) for r in records), len(records)),
                framed_share=share(sum(r.get('framed', False) for r in records), len(records)),
                incomplete_or_none_share=share(level('accurate_incomplete') + level('none'), n), cut_pairs=sum(r['cut'] for r in rows))


def measures(table: Mapping[str, Mapping[str, Mapping[str, Any]]], decided: Mapping[str, Mapping[str, Any]], multi: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    outcomes = pair_outcomes(table, decided)
    summaries = {arm: arm_summary(outcomes[arm]) for arm in ARMS}
    both = lambda first, second, **kw: compare(outcomes, first, second, **kw)
    truncation = [both('u', 'b1'), both('u', 'b2')]
    over = both('x1', 'u')
    noise = both('b2', 'b1')
    lowest = lambda field: min((summaries[a][field] for a in ('b1', 'b2') if summaries[a][field] is not None), default=None)
    guards = {}
    for arm in ('u', 'x1'):
        s = summaries[arm]
        guards[arm] = dict(accuracy=s['accuracy'] is not None and s['accuracy'] + 1e-9 >= ACCURACY_BAR,
                           wrong_not_above_lowest_block_plus_one=s['wrong'] <= min(summaries['b1']['wrong'], summaries['b2']['wrong']) + 1,
                           recall=s['recall'] is not None and s['recall'] + 1e-9 >= RECALL_SHARE * lowest('recall'),
                           flagged=s['flagged_share'] is not None and s['flagged_share'] <= FLAG_LIMIT + 1e-9,
                           framed=s['framed_share'] is not None and s['framed_share'] + 1e-9 >= lowest('framed_share'))
        guards[arm]['all'] = all(guards[arm].values())
    shared = [k for k in outcomes['x1'] if k in outcomes['u']]
    fragmentation = dict(pairs=len(shared), x1=sum(outcomes['x1'][k]['outcome'] <= 2 and outcomes['x1'][k]['level'] != 'wrong' for k in shared) / len(shared) if shared else None,
                         u=sum(outcomes['u'][k]['outcome'] <= 2 and outcomes['u'][k]['level'] != 'wrong' for k in shared) / len(shared) if shared else None)
    fragmentation['within_margin'] = None if not shared else fragmentation['x1'] <= fragmentation['u'] + FRAGMENT_MARGIN + 1e-9
    over_verdict = verdict([over])
    if over_verdict == 'improved' and not ((summaries['x1']['blended_share'] or 0) <= (summaries['u']['blended_share'] or 0) + 1e-9
                                           and (summaries['x1']['misfit_share'] or 0) <= (summaries['u']['misfit_share'] or 0) + 1e-9):
        over_verdict = 'not shown'          # 28.8: improved over U only if focus and misfit are no worse too
    result = dict(per_arm=summaries, truncation=dict(verdict=verdict(truncation), against_b1=truncation[0], against_b2=truncation[1]),
                  over_inclusion=dict(verdict=over_verdict, comparison=over, guards_hold=guards['x1']['all'], fragmentation=fragmentation),
                  noise_floor=noise, production_question=dict(u_against_b1=truncation[0], u_against_b2=truncation[1], x1_against_b1=both('x1', 'b1'), x1_against_b2=both('x1', 'b2')),
                  guards=guards, without_sermon_1502=dict(u_against_b1=both('u', 'b1', exclude_video=1502), u_against_b2=both('u', 'b2', exclude_video=1502),
                                                          x1_against_u=both('x1', 'u', exclude_video=1502)))
    if multi:
        result['multi_record'] = multi
    return result


def padding(decided: Mapping[str, Mapping[str, Any]], queue: Mapping[str, Any], versions: Mapping[str, Any]) -> dict[str, Any]:
    """Per arm, the distinct-points labels of its multi-record pairs; the reading (same point twice at most 15%) only with at least MIN_MULTI such pairs."""
    result = {}
    for arm in MULTI_ARMS:
        labels = [decided[i['id']]['level'] for i in queue['items'] if i['kind'] == 'distinct' and arm in versions['arms'][i['id']]]
        same = sum(level == 'same_point_twice' for level in labels)
        result[arm] = dict(multi_record_pairs=len(labels), distinct=sum(level == 'distinct' for level in labels), overlapping=sum(level == 'overlapping' for level in labels),
                           same_point_twice=same, reading=None if len(labels) < MIN_MULTI else same / len(labels) <= SAME_POINT_LIMIT + 1e-9)
    return result


def sample_agreement(queue: Mapping[str, Any], versions: Mapping[str, Any], mine: Mapping[str, Mapping[str, Any]], human: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Brian's version-blind sample against my labels, item by item, and the level counts per arm on his labels next to mine."""
    items = [i for i in queue['items'] if i['kind'] == 'record' and i['id'] in human]
    agree = sum(mine[i['id']]['level'] == human[i['id']]['level'] for i in items)
    per_arm = {arm: dict(items=sum(arm in versions['arms'][i['id']] for i in items),
                         mine={lv: sum(arm in versions['arms'][i['id']] and mine[i['id']]['level'] == lv for i in items) for lv in LEVELS.values()},
                         brian={lv: sum(arm in versions['arms'][i['id']] and human[i['id']]['level'] == lv for i in items) for lv in LEVELS.values()}) for arm in ('u', 'x1')}
    return dict(items=len(items), agree=agree, disagreements=[dict(item=i['id'], mine=mine[i['id']]['level'], brian=human[i['id']]['level']) for i in items
                                                         if mine[i['id']]['level'] != human[i['id']]['level']], per_arm=per_arm)


def report(base_dir: Path, set_id: str = 'v2') -> dict[str, Any]:
    out = paths(base_dir, set_id)
    queue, versions = leaf_review._sealed(out['queue']), leaf_review._sealed(out['versions'])
    decided = leaf_review.load_decisions(base_dir, leaf_evidence.V4, dict(decisions=out['decisions']))
    missing = [i['id'] for i in queue['items'] if i['id'] not in decided]
    if missing:
        raise ValueError(f'{len(missing)} items are unlabeled')
    table = matched(base_dir, set_id)
    result = dict(version=VERSION, set_id=set_id, labels_by=sorted({d['source'] for d in decided.values()}), **measures(table, decided),
                  missing_requests={arm: sorted(k for k, c in cells.items() if c['state'] == 'missing') for arm, cells in table.items()},
                  padding=padding(decided, queue, versions))
    human = leaf_review.load_decisions(base_dir, leaf_evidence.V4, dict(decisions=out['human']))
    if human:
        result['brian_sample'] = sample_agreement(queue, versions, decided, human)
    second = leaf_review.load_decisions(base_dir, leaf_evidence.V4, dict(decisions=out['second']))
    if second:
        result['second_rater'] = second_agreement(queue, decided, second)
    write_json(out['report_json'], result)
    out['report_md'].write_text(render_report(result))
    return dict(result, report_md=str(out['report_md']), report_json=str(out['report_json']))


def _pct(value: float | None) -> str:
    return 'n/a' if value is None else f'{value:.0%}'


def render_report(result: Mapping[str, Any]) -> str:
    lines = ['# Stage 3 unit test (section 28.8)', '', f"Labels by {result['labels_by']}. One run per arm; the readings are the pre-stated ones of 28.8 and are reported as they fall.", '',
             '| Arm | pairs | complete | incomplete | no record | wrong | accuracy (95% interval) | recall | flagged | blended | misfit | cut pairs |', '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for arm, s in result['per_arm'].items():
        lines.append(f"| {arm} | {s['pairs']} | {s['complete']} | {s['accurate_incomplete']} | {s['no_record']} | {s['wrong']} | {_pct(s['accuracy'])} {s['accuracy_interval']} | "
                     f"{_pct(s['recall'])} | {_pct(s['flagged_share'])} | {_pct(s['blended_share'])} | {_pct(s['misfit_share'])} | {s['cut_pairs']} |")
    fmt = lambda c: f"wins {c['wins']}, losses {c['losses']}, ties {c['ties']} over {c['blocks']} blocks ({c['pairs']} pairs); one-sided p {c['p_first_better']}; mean difference {c['mean_difference']}, sermon bootstrap {c['bootstrap']}"
    lines += ['', f"**Truncation reading (units against blocks): {result['truncation']['verdict']}.**", f"- U against B1: {fmt(result['truncation']['against_b1'])}",
              f"- U against B2: {fmt(result['truncation']['against_b2'])}", f"- Noise floor, B2 against B1: {fmt(result['noise_floor'])}", '',
              f"**Over-inclusion reading (sub-unit against unit): {result['over_inclusion']['verdict']}.** Guards for X1 hold: {result['over_inclusion']['guards_hold']}.",
              f"- X1 against U: {fmt(result['over_inclusion']['comparison'])}", f"- Fragmentation (incomplete or no record, over the shared pairs): {result['over_inclusion']['fragmentation']}", '',
              '**Production question (no verdict):**'] + [f"- {name.replace('_', ' ')}: {fmt(c)}" for name, c in result['production_question'].items()]
    lines += ['', '**Guards:** ' + '; '.join(f"{arm}: {g}" for arm, g in result['guards'].items()), '', '**Without sermon 1502:** ' + '; '.join(f"{n.replace('_', ' ')}: {fmt(c)}" for n, c in result['without_sermon_1502'].items()),
              '', f"**Padding (distinct points, multi-record pairs):** {result['padding']}", '', f"**Requests with no result (transport failure, left out of that arm):** {result['missing_requests']}"]
    if 'second_rater' in result:
        lines += ['', f"**Second rater (Claude) against the rater of record:** {result['second_rater']}"]
    if 'brian_sample' in result:
        lines += ['', f"**Brian's sample:** {result['brian_sample']['agree']} of {result['brian_sample']['items']} levels agree; per arm: {result['brian_sample']['per_arm']}; disagreements: {result['brian_sample']['disagreements']}"]
    return '\n'.join(lines) + '\n'
